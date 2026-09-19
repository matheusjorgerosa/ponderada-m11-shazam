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
import tempfile
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


# Normalizar por PICO nao resolve: chuva e vento tem pico alto e RMS baixo, e
# chegam no mic quase no nivel do ambiente. Normalizar por RMS iguala a energia
# percebida entre os clipes, que e o que o detector enxerga.
RMS_ALVO = 10 ** (-18 / 20)     # -18 dBFS
PICO_MAX = 10 ** (-1 / 20)      # teto de -1 dBFS, pra nao ceifar impulsivos

_cache_norm: dict[Path, Path] = {}


def normaliza(wav: Path) -> Path:
    """Copia o clipe com RMS padronizado, num arquivo temporario reaproveitado."""
    if wav in _cache_norm:
        return _cache_norm[wav]

    import numpy as np
    import soundfile as sf

    y, sr = sf.read(wav, dtype="float32", always_2d=False)
    if y.ndim > 1:
        y = y.mean(axis=1)

    rms = float(np.sqrt(np.mean(y ** 2)))
    if rms > 1e-9:
        y = y * (RMS_ALVO / rms)
    pico = float(np.abs(y).max())
    if pico > PICO_MAX:
        y = y * (PICO_MAX / pico)

    destino = Path(tempfile.gettempdir()) / f"bench_{wav.stem}.wav"
    sf.write(destino, y, sr)
    _cache_norm[wav] = destino
    return destino


def toca(wav: Path) -> None:
    """Toca e espera terminar. aplay porque o ESC-50 e WAV 44,1 kHz mono."""
    subprocess.run(["aplay", "-q", str(normaliza(wav))], check=False,
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


# ------------------------------------------------------- avaliacao offline
def modo_offline(nivel_alvo: str, seed: int) -> int:
    """Avalia sem emitir som: passa o ESC-50 pelo dsp.py e pontua com o .onnx.

    Isto e legitimo porque os dois lados ja estao amarrados por teste:
    features.c concorda com librosa/scipy em ~1e-6 e detector.c concorda com o
    .onnx em ~1e-7. As features que o Python calcula sao as que o device
    produziria com aquele audio na entrada.

    O que NAO e medido aqui: a latencia acustica real e a resposta do
    alto-falante e da sala. Isso exige o modo --avaliar.
    """
    import numpy as np
    import onnxruntime as ort
    sys.path.insert(0, str(ROOT / "tools/dashboard"))
    import dsp

    normal = np.genfromtxt(ROOT / "model/data/normal.csv", delimiter=",",
                           skip_header=1, dtype=np.float32)
    normal = normal[~np.isnan(normal).any(axis=1)]
    if len(normal) < 100:
        sys.exit("model/data/normal.csv insuficiente — colete o ambiente antes")

    # Mesmo split do train.py (mesma seed), pra avaliar so no que o treino
    # nao viu.
    M = P["model"]
    rng = np.random.default_rng(M["seed"])
    idx = rng.permutation(len(normal))
    val = normal[idx[int(len(normal) * (1 - M["val_split"])):]]

    amb_rms = np.percentile(normal[:, 0], [10, 50, 90])
    print(f"ambiente: RMS p10={amb_rms[0]:.5f} p50={amb_rms[1]:.5f} "
          f"p90={amb_rms[2]:.5f}  ({len(val)} frames de validacao)")

    sess = ort.InferenceSession(str(ROOT / "model/anomaly_detector.onnx"))
    thr = _threshold()
    deb = P["detector"]["debounce_n"]

    def decide(feats: np.ndarray) -> bool:
        """Mesma regra do device: DEBOUNCE_N frames consecutivos acima."""
        _, sc = sess.run(None, {"features": feats.astype(np.float32)})
        seguidos = 0
        for v in sc:
            seguidos = seguidos + 1 if v > thr else 0
            if seguidos >= deb:
                return True
        return False

    # Falso positivo: o ambiente de validacao, em janelas do tamanho de um clipe.
    janela = int(5 * dsp.SR / dsp.HOP)
    fp = blocos = 0
    for i in range(0, len(val) - janela, janela):
        blocos += 1
        fp += decide(val[i:i + janela])

    cat = catalogo()
    clipes = [w for c in ANOMALIAS for w in cat.get(c, [])]
    # GRUPO DE CONTROLE: sons de fundo continuos, que NAO deveriam disparar.
    # Sem ele este teste nao pode falhar — mede-se "o detector dispara?" e a
    # resposta e sempre sim, porque o ESC-50 e audio limpo e o treino veio do
    # microfone real. Se o controle disparar tanto quanto a anomalia, o numero
    # de deteccao nao significa nada.
    controle = [w for c in NORMAIS for w in cat.get(c, [])]
    random.Random(seed).shuffle(clipes)
    random.Random(seed).shuffle(controle)

    niveis = {"igual": amb_rms[1], "p90": amb_rms[2],
              "+10dB": amb_rms[2] * 3.16, "+20dB": amb_rms[2] * 10.0}
    if nivel_alvo != "todos":
        niveis = {nivel_alvo: niveis[nivel_alvo]}

    print(f"\n{len(clipes)} clipes de anomalia · {len(controle)} de controle · "
          f"threshold {thr:.6f} · debounce {deb}\n")
    print(f"{'nivel':<10}{'RMS alvo':>11}{'anomalia':>11}{'controle':>11}{'separacao':>12}")
    print("-" * 56)

    import soundfile as sf
    for nome, alvo in niveis.items():
        taxas = {}
        for rotulo, conjunto in (("anomalia", clipes), ("controle", controle)):
            vp = 0
            for w in conjunto:
                y, sr = sf.read(w, dtype="float32", always_2d=False)
                if y.ndim > 1:
                    y = y.mean(axis=1)
                y = np.interp(np.linspace(0, len(y) - 1, int(len(y) * dsp.SR / sr)),
                              np.arange(len(y)), y).astype(np.float32)
                r = float(np.sqrt(np.mean(y ** 2)))
                if r > 1e-9:
                    y = y * (alvo / r)
                # Piso de ruido: sem ele os trechos silenciosos do clipe caem
                # no piso da mel (-102.97 no mfcc0), que e um valor que
                # microfone nenhum produz e dispararia por motivo errado.
                y = y + np.random.default_rng(0).normal(
                    0, amb_rms[0], len(y)).astype(np.float32)

                feats = np.array([dsp.features(y[i:i + dsp.N])
                                  for i in range(0, len(y) - dsp.N + 1, dsp.HOP)])
                if len(feats) and decide(feats):
                    vp += 1
            taxas[rotulo] = vp / len(conjunto)

        sep = taxas["anomalia"] - taxas["controle"]
        print(f"{nome:<10}{alvo:>11.5f}{taxas['anomalia']:>10.0%}"
              f"{taxas['controle']:>11.0%}{sep:>11.0%}")

    print(f"\nfalso positivo no ambiente real (do microfone): "
          f"{fp}/{blocos} janelas de 5 s ({fp/max(blocos,1):.1%})")

    print("\nCOMO LER: a coluna que importa e 'separacao'. Se o controle")
    print("disparar tanto quanto a anomalia, o detector esta reagindo a")
    print("diferenca de dominio (audio limpo do ESC-50 contra audio do")
    print("INMP441), nao ao conteudo — e a taxa de deteccao nao significa")
    print("nada. So o modo --avaliar, com som pelo alto-falante, mede")
    print("acuracia de verdade: ali as duas classes passam pelo mesmo")
    print("microfone e pela mesma sala.")
    return 0


def _threshold() -> float:
    import re
    txt = (ROOT / "firmware/include/model_weights.h").read_text()
    return float(re.search(r"model_threshold\s*=\s*([-+0-9.eE]+)f", txt).group(1))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--baixar-esc50", action="store_true")
    ap.add_argument("--treino", action="store_true")
    ap.add_argument("--avaliar", action="store_true")
    ap.add_argument("--offline", action="store_true",
                    help="avalia sem emitir som, processando o ESC-50 em Python")
    ap.add_argument("--nivel", default="todos",
                    choices=["todos", "igual", "p90", "+10dB", "+20dB"])
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
    if args.offline:
        return modo_offline(args.nivel, args.seed)
    if not (args.treino or args.avaliar):
        ap.error("escolha --treino, --avaliar ou --offline")
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
