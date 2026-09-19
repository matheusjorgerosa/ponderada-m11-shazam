#!/usr/bin/env python3
"""Le a serial do ESP32 e grava as 15 features num CSV.

Aceita as duas saidas do firmware sem precisar reconfigurar nada:
  - MODE_DATASET=1  -> CSV puro, uma linha de 15 floats por frame
  - MODE_STREAM=1   -> linhas "S,..." do dashboard, de onde extraimos as features

    .venv/bin/python model/collect.py --minutos 10 --saida model/data/normal.csv
    .venv/bin/python model/collect.py --minutos 1  --saida model/data/anomaly.csv

Os ~10 minutos de som normal definem o que o modelo considera normal — colete
no mesmo ambiente onde vai demonstrar. O minuto de anomalias nao treina nada;
serve pra validar o threshold.
"""
import argparse
import csv
import glob
import json
import sys
import time
from pathlib import Path

import serial

ROOT = Path(__file__).resolve().parents[1]
P = json.loads((ROOT / "params.json").read_text())
BAUD = P["serial"]["baud"]
N_MFCC = P["n_mfcc"]
N_BANDS = P["n_bands"]
N_FEAT = 2 + N_MFCC
FPS = P["sample_rate"] / P["frame_size"]

COLUNAS = ["rms", "centroid"] + [f"mfcc{i}" for i in range(N_MFCC)]


def acha_porta() -> str | None:
    portas = sorted(glob.glob("/dev/ttyUSB*") + glob.glob("/dev/ttyACM*"))
    return portas[0] if portas else None


def extrai(linha: str) -> list[float] | None:
    """Devolve as 15 features, venham de que modo vier."""
    p = linha.split(",")

    if p[0] == "S":
        # S,<t_us>,<rms>,<centroid>,<score>,<threshold>,<13 mfccs>,<64 bandas>
        #
        # Os MFCCs sao localizados a partir do FIM da linha, nao por indice
        # fixo. Ja quebrou uma vez: o campo threshold entrou no stream depois
        # e o indice fixo passou a rejeitar TODA linha, em silencio, com o CSV
        # saindo vazio. Contar do fim sobrevive a campos novos no cabecalho.
        if len(p) < 5 + N_MFCC + N_BANDS:
            return None
        campos = [p[2], p[3]] + p[-(N_BANDS + N_MFCC):-N_BANDS]
    elif len(p) == N_FEAT:
        campos = p
    else:
        return None

    try:
        return [float(v) for v in campos]
    except ValueError:
        return None   # o cabecalho do MODE_DATASET cai aqui, e tudo bem


# Roteiro do modo guiado: (segundo de inicio, texto, gravar?).
# So os trechos com gravar=True entram no CSV — o silencio entre eles e
# ambiente, e ambiente no anomaly.csv diluiria a taxa de deteccao.
ROTEIRO = [
    (0,  "prepare-se — fique a uns 30 cm do microfone", False),
    (4,  ">>> BATA PALMAS, uma a cada segundo", True),
    (16, "pausa", False),
    (19, ">>> ASSOBIE, variando de grave para agudo", True),
    (31, "pausa", False),
    (34, ">>> BATA NA MESA com os nos dos dedos", True),
    (46, "pausa", False),
    (49, ">>> FALE em voz normal, qualquer coisa", True),
    (61, "pronto", False),
]


def guiado(ser: serial.Serial, w) -> int:
    """Avisa na hora de cada som e grava so durante as janelas ativas."""
    t0 = time.time()
    n, i = 0, -1
    gravando = False

    while True:
        agora = time.time() - t0
        while i + 1 < len(ROTEIRO) and agora >= ROTEIRO[i + 1][0]:
            i += 1
            _, texto, gravando = ROTEIRO[i]
            print(f"\n[{ROTEIRO[i][0]:>2}s] {texto}", flush=True)
        if agora >= ROTEIRO[-1][0]:
            break

        linha = ser.readline().decode("utf-8", "replace").strip()
        if not linha:
            continue
        feats = extrai(linha)
        if feats is None or not gravando:
            continue
        w.writerow([f"{v:.6f}" for v in feats])
        n += 1
        print(f"\r  {n} frames", end="", flush=True)

    print()
    return n


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutos", type=float, default=10.0)
    ap.add_argument("--saida", default="model/data/normal.csv")
    ap.add_argument("--port", default=None, help="padrao: autodetecta")
    ap.add_argument("--guiado", action="store_true",
                    help="roteiro de sons; grava so durante as janelas ativas")
    args = ap.parse_args()

    porta = args.port or acha_porta()
    if not porta:
        print("nenhuma /dev/ttyUSB* ou /dev/ttyACM* encontrada", file=sys.stderr)
        return 1

    saida = Path(args.saida)
    saida.parent.mkdir(parents=True, exist_ok=True)
    alvo = int(args.minutos * 60 * FPS)

    print(f"{porta} @ {BAUD} -> {saida}")
    if args.guiado:
        print(f"modo guiado: {ROTEIRO[-1][0]} s, "
              f"{sum(b[0]-a[0] for a, b in zip(ROTEIRO, ROTEIRO[1:]) if a[2])} s de som")
    else:
        print(f"coletando {args.minutos:g} min ~= {alvo} frames "
              f"(Ctrl-C para parar antes)")

    n, ignoradas, t0 = 0, 0, time.time()
    try:
        with serial.Serial(porta, BAUD, timeout=2) as ser, \
             saida.open("w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(COLUNAS)

            if args.guiado:
                n = guiado(ser, w)
                print(f"\n{n} frames em {saida}")
                return 0

            while n < alvo:
                linha = ser.readline().decode("utf-8", "replace").strip()
                if not linha:
                    continue
                feats = extrai(linha)
                if feats is None:
                    ignoradas += 1
                    continue
                w.writerow([f"{v:.6f}" for v in feats])
                n += 1
                if n % 50 == 0:
                    dt = time.time() - t0
                    print(f"\r{n}/{alvo} frames · {n/max(dt,1e-9):.1f} fps · "
                          f"{dt:.0f}s decorridos", end="", flush=True)
    except KeyboardInterrupt:
        print("\ninterrompido")

    print(f"\n{n} frames em {saida} ({ignoradas} linhas ignoradas)")
    if n < alvo * 0.9:
        print("AVISO: coletou bem menos que o pedido — confira o cabo e o modo do firmware")
    return 0


if __name__ == "__main__":
    sys.exit(main())
