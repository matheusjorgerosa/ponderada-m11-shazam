#!/usr/bin/env python3
"""Banca de testes: toca WAVs pelo alto-falante e mede o que o device detecta.

    # 1. baixa o ESC-50 (~600 MB, uma vez so)
    .venv/bin/python tests/test_bench.py --baixar-esc50

    # 2. toca sons de fundo e grava as features -> normal.csv
    .venv/bin/python tests/test_bench.py --treino --minutos 8

    # 3. retreina com esses dados
    .venv/bin/python model/train.py

    # 4. avalia: sequencia mista com anomalias em instantes conhecidos
    .venv/bin/python tests/test_bench.py --avaliar

Por que o passo 2 existe: o autoencoder aprende o perfil acustico do ambiente
em que foi treinado. Se voce treinar so com a sala em silencio e avaliar
tocando ESC-50 no alto-falante, TUDO vira anomalia — inclusive os clipes que
deveriam ser normais — e a taxa de falso positivo perde o sentido. Os clipes
normais precisam estar na distribuicao de treino.
"""
import argparse
import csv
import io
import json
import random
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import zipfile
from pathlib import Path

import serial

ROOT = Path(__file__).resolve().parents[1]
P = json.loads((ROOT / "params.json").read_text())
BAUD = P["serial"]["baud"]
N_MFCC = P["n_mfcc"]
N_BANDS = P["n_bands"]

ESC50_URL = "https://github.com/karoldvl/ESC-50/archive/master.zip"
ESC50_DIR = ROOT / "tests/data/ESC-50-master"

# Sons de fundo continuos: e o que um ambiente "normal" produz.
NORMAIS = ["rain", "wind", "crickets", "vacuum_cleaner", "washing_machine",
           "engine", "water_drops", "clock_tick"]
# Eventos abruptos, que e o que o detector tem que pegar.
ANOMALIAS = ["clapping", "glass_breaking", "door_wood_knock", "can_opening",
             "siren", "dog", "hand_saw"]

CSV_COLUNAS = ["rms", "centroid"] + [f"mfcc{i}" for i in range(N_MFCC)]


# --------------------------------------------------------------- ESC-50
def baixar_esc50() -> None:
    if ESC50_DIR.exists():
        print(f"ja existe: {ESC50_DIR.relative_to(ROOT)}")
        return
    ESC50_DIR.parent.mkdir(parents=True, exist_ok=True)
    print(f"baixando {ESC50_URL} (~600 MB)…")
    with urllib.request.urlopen(ESC50_URL) as r:
        dados = r.read()
    print("extraindo…")
    zipfile.ZipFile(io.BytesIO(dados)).extractall(ESC50_DIR.parent)
    print(f"pronto: {ESC50_DIR.relative_to(ROOT)}")


def catalogo() -> dict[str, list[Path]]:
    meta = ESC50_DIR / "meta/esc50.csv"
    if not meta.exists():
        sys.exit("ESC-50 nao encontrado. Rode com --baixar-esc50 primeiro.")
    por_categoria: dict[str, list[Path]] = {}
    with meta.open() as fh:
        for linha in csv.DictReader(fh):
            wav = ESC50_DIR / "audio" / linha["filename"]
            if wav.exists():
                por_categoria.setdefault(linha["category"], []).append(wav)
    return por_categoria


def toca(wav: Path) -> None:
    """Toca e espera terminar. aplay porque o ESC-50 e WAV 44,1 kHz mono."""
    subprocess.run(["aplay", "-q", str(wav)], check=False,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# --------------------------------------------------------------- serial
class Leitor(threading.Thread):
    """Le a serial numa thread e carimba a hora de chegada de cada linha."""

    def __init__(self, porta: str):
        super().__init__(daemon=True)
        self.porta = porta
        self.parar = False
        self.deteccoes: list[float] = []     # instante de cada anomalia
        self.features: list[list[float]] = []
        self.erro: str | None = None

    def run(self) -> None:
        try:
            with serial.Serial(self.porta, BAUD, timeout=0.5) as s:
                buf = b""
                while not self.parar:
                    buf += s.read(8192)
                    *linhas, buf = buf.split(b"\n")
                    agora = time.time()
                    for bl in linhas:
                        self._linha(bl.decode("utf-8", "replace").strip(), agora)
        except Exception as e:                # noqa: BLE001
            self.erro = str(e)

    def _linha(self, l: str, agora: float) -> None:
        p = l.split(",")
        if l.startswith("D,") and len(p) == 8 and p[4] == "1":
            self.deteccoes.append(agora)
        elif l.startswith("S,") and len(p) == 6 + N_MFCC + N_BANDS:
            try:
                self.features.append([float(p[2]), float(p[3])] +
                                     [float(v) for v in p[6:6 + N_MFCC]])
            except ValueError:
                pass


def acha_porta(arg: str | None) -> str:
    if arg:
        return arg
    import glob
    portas = sorted(glob.glob("/dev/ttyUSB*") + glob.glob("/dev/ttyACM*"))
    if not portas:
        sys.exit("nenhuma porta serial encontrada")
    return portas[0]


# --------------------------------------------------------------- modos
def modo_treino(leitor: Leitor, cat: dict, minutos: float, saida: Path) -> None:
    clipes = [w for c in NORMAIS for w in cat.get(c, [])]
    random.shuffle(clipes)
    print(f"tocando sons de fundo por {minutos:g} min "
          f"({len(clipes)} clipes disponiveis)")

    fim = time.time() + minutos * 60
    i = 0
    while time.time() < fim:
        toca(clipes[i % len(clipes)])
        i += 1
        print(f"\r{i} clipes · {len(leitor.features)} frames · "
              f"{fim - time.time():.0f}s restantes", end="", flush=True)
    print()

    saida.parent.mkdir(parents=True, exist_ok=True)
    with saida.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(CSV_COLUNAS)
        w.writerows([f"{v:.6f}" for v in linha] for linha in leitor.features)
    print(f"{len(leitor.features)} frames -> {saida.relative_to(ROOT)}")


def modo_avaliar(leitor: Leitor, cat: dict, n_eventos: int,
                 janela: float) -> int:
    normais = [w for c in NORMAIS for w in cat.get(c, [])]
    anomalos = [w for c in ANOMALIAS for w in cat.get(c, [])]
    random.shuffle(normais)
    random.shuffle(anomalos)

    # Alterna: dois clipes normais, um anomalo. Guarda o instante de cada um.
    roteiro = []
    for k in range(n_eventos):
        roteiro.append(("normal", normais[(2 * k) % len(normais)]))
        roteiro.append(("normal", normais[(2 * k + 1) % len(normais)]))
        roteiro.append(("anomalia", anomalos[k % len(anomalos)]))

    print(f"tocando {len(roteiro)} clipes de 5 s "
          f"({n_eventos} anomalias)\n")
    eventos = []
    for tipo, wav in roteiro:
        t0 = time.time()
        print(f"  {time.strftime('%H:%M:%S')} {tipo:<9} {wav.name}")
        toca(wav)
        eventos.append((tipo, t0, time.time()))

    time.sleep(1.5)     # o pipeline tem ~0,2 s de latencia mais o debounce
    leitor.parar = True
    time.sleep(0.8)

    # Uma anomalia conta como detectada se houve alerta entre o inicio do
    # clipe e `janela` segundos apos o fim dele.
    vp = fn = fp = 0
    atrasos = []
    usadas = set()
    for tipo, ini, fim in eventos:
        achou = [d for d in leitor.deteccoes if ini <= d <= fim + janela]
        if tipo == "anomalia":
            if achou:
                vp += 1
                atrasos.append(achou[0] - ini)
                usadas.update(achou)
            else:
                fn += 1
        else:
            novas = [d for d in achou if d not in usadas]
            fp += len(novas)
            usadas.update(novas)

    print(f"\n{'':>14}{'previu normal':>16}{'previu anomalia':>18}")
    print(f"{'normal':>14}{'—':>16}{fp:>18}")
    print(f"{'anomalia':>14}{fn:>16}{vp:>18}")
    total = vp + fn
    print(f"\nverdadeiro positivo: {vp}/{total} ({100*vp/max(total,1):.0f}%)")
    print(f"falso negativo:      {fn}/{total}")
    print(f"falso positivo:      {fp} em {2*n_eventos} clipes normais")
    if atrasos:
        atrasos.sort()
        print(f"latencia de deteccao: mediana {atrasos[len(atrasos)//2]*1000:.0f} ms"
              f" · max {atrasos[-1]*1000:.0f} ms")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--baixar-esc50", action="store_true")
    ap.add_argument("--treino", action="store_true")
    ap.add_argument("--avaliar", action="store_true")
    ap.add_argument("--minutos", type=float, default=8.0)
    ap.add_argument("--eventos", type=int, default=15)
    ap.add_argument("--janela", type=float, default=1.0,
                    help="segundos apos o clipe em que um alerta ainda conta")
    ap.add_argument("--saida", default="model/data/normal.csv")
    ap.add_argument("--port", default=None)
    ap.add_argument("--seed", type=int, default=P["model"]["seed"])
    args = ap.parse_args()

    if args.baixar_esc50:
        baixar_esc50()
        return 0
    if not (args.treino or args.avaliar):
        ap.error("escolha --treino ou --avaliar")
    if not shutil.which("aplay"):
        sys.exit("aplay nao encontrado (instale alsa-utils)")

    random.seed(args.seed)
    cat = catalogo()
    leitor = Leitor(acha_porta(args.port))
    leitor.start()
    time.sleep(1.0)
    if leitor.erro:
        sys.exit(f"serial: {leitor.erro}")

    try:
        if args.treino:
            modo_treino(leitor, cat, args.minutos, ROOT / args.saida)
            return 0
        return modo_avaliar(leitor, cat, args.eventos, args.janela)
    finally:
        leitor.parar = True


if __name__ == "__main__":
    sys.exit(main())
