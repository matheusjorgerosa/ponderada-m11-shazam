#!/usr/bin/env python3
"""Monitor ao vivo no terminal: score, threshold e alertas de anomalia.

    .venv/bin/python tools/monitor.py

Uma linha de status que se reescreve a cada frame, com um sparkline dos
ultimos segundos, e uma linha permanente a cada anomalia detectada.

Le as linhas que o firmware ja emite:
    D,<seq>,<score>,<threshold>,<anomalia>,<cap_feat_us>,<feat_det_us>,<total_us>
    S,<t_us>,<rms>,<centroid>,...
"""
import argparse
import glob
import json
import sys
import time
from collections import deque
from pathlib import Path

import serial

ROOT = Path(__file__).resolve().parents[1]
P = json.loads((ROOT / "params.json").read_text())
BAUD = P["serial"]["baud"]

BLOCOS = "▁▂▃▄▅▆▇█"
N_SPARK = 56

# 38=vermelho 32=verde 33=amarelo 90=cinza 1=negrito
C = lambda s, c: f"\033[{c}m{s}\033[0m"


def acha_porta(arg):
    if arg:
        return arg
    p = sorted(glob.glob("/dev/ttyUSB*") + glob.glob("/dev/ttyACM*"))
    if not p:
        sys.exit("nenhuma porta serial encontrada — o ESP32 esta plugado?")
    return p[0]


def spark(scores, thr):
    """Sparkline em escala log relativa ao threshold; acima dele fica vermelho."""
    if not scores:
        return " " * N_SPARK
    import math
    saida = []
    for v in scores:
        r = math.log10(max(v, 1e-6) / thr)          # 0 = exatamente no limiar
        i = min(max(int((r + 2.0) / 3.0 * 7), 0), 7)  # -2..+1 decadas -> 0..7
        ch = BLOCOS[i]
        saida.append(C(ch, "31") if v > thr else C(ch, "32"))
    return "".join(saida)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default=None)
    args = ap.parse_args()
    porta = acha_porta(args.port)

    scores = deque(maxlen=N_SPARK)
    rms = cent = 0.0
    thr = None
    alertas = 0
    t0 = time.time()
    ultimo_desenho = 0.0

    print(f"{porta} @ {BAUD} · Ctrl-C para sair\n")
    try:
        with serial.Serial(porta, BAUD, timeout=1) as s:
            buf = b""
            while True:
                buf += s.read(4096)
                *linhas, buf = buf.split(b"\n")
                for bl in linhas:
                    l = bl.decode("utf-8", "replace").strip()
                    p = l.split(",")

                    if l.startswith("S,") and len(p) > 4:
                        try:
                            rms, cent = float(p[2]), float(p[3])
                        except ValueError:
                            pass

                    elif l.startswith("D,") and len(p) == 8:
                        try:
                            sc, thr = float(p[2]), float(p[3])
                            anom, lat = p[4] == "1", int(p[7])
                        except ValueError:
                            continue
                        scores.append(sc)
                        if anom:
                            alertas += 1
                            print(f"\r\033[K{C('  ANOMALIA', '1;31')}  "
                                  f"{time.strftime('%H:%M:%S')}  "
                                  f"score {C(f'{sc:7.3f}', '31')} "
                                  f"= {C(f'{sc/thr:5.1f}x', '31')} o limiar  ·  "
                                  f"rms {rms:.4f}  centroide {cent:5.0f} Hz  ·  "
                                  f"latencia {lat/1000:.2f} ms")

                    elif l.startswith("I (") or l.startswith("E (") or l.startswith("W ("):
                        print(f"\r\033[K{C(l, '90')}")

                agora = time.time()
                if thr and agora - ultimo_desenho > 0.1:
                    ultimo_desenho = agora
                    atual = scores[-1] if scores else 0.0
                    m, sg = divmod(int(agora - t0), 60)
                    cor = "31" if atual > thr else "32"

                    # Se o ambiente inteiro esta acima do limiar, o modelo nao
                    # conhece esta sala. O alerta dispara uma vez e nunca
                    # rearma (so rearma quando o score volta abaixo), entao o
                    # sintoma e enganoso: parece parado, esta e saturado.
                    acima = sum(v > thr for v in scores) / max(len(scores), 1)
                    aviso = ""
                    if len(scores) == N_SPARK and acima > 0.5:
                        aviso = C("  MODELO DESATUALIZADO PARA ESTE AMBIENTE"
                                  " — recolete e retreine", "1;33")

                    print(f"\r\033[K{spark(scores, thr)}  "
                          f"score {C(f'{atual:6.3f}', cor)}/{thr:.3f}  "
                          f"rms {rms:.4f}  cent {cent:5.0f}Hz  "
                          f"{C(f'{alertas} alertas', '33' if alertas else '90')}  "
                          f"{m:02d}:{sg:02d}{aviso}", end="", flush=True)
    except KeyboardInterrupt:
        pass
    except serial.SerialException as e:
        sys.exit(f"\nserial: {e}")

    dur = time.time() - t0
    print(f"\n\n{alertas} alertas em {dur/60:.1f} min "
          f"({alertas/max(dur/60,1e-9):.1f} por minuto)")


if __name__ == "__main__":
    main()
