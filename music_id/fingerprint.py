#!/usr/bin/env python3
"""Fingerprinting de musica — constellation map e hashing combinatorio.

Mesmo pipeline que roda no ESP32, reaproveitando o dsp.py (que por sua vez e
validado contra o features.c em igualdade exata no peak picking).

    # so olhar o que sai de uma musica
    .venv/bin/python music_id/fingerprint.py music_id/songs/01-nome.mp3

O banco de verdade e montado pelo build_db.py, que importa daqui.

Como funciona, em tres passos:
  1. Picos — o pico mais forte de cada super-banda por frame, acima da media
     do frame. Isso e a "constellation map": a musica vira um punhado de
     pontos (tempo, frequencia) robustos a ruido e a volume.
  2. Hashing — cada pico ancora pareia com os LEQUE picos seguintes dentro de
     DT_MAX frames. O par (f1, f2, dt) vira um hash de 21 bits. Pares sao
     muito mais discriminativos que picos isolados.
  3. Fases — o device amostra em fase arbitraria em relacao a esta analise, e
     um transiente na fronteira de dois frames muda os picos. Geramos o banco
     em N_FASES deslocamentos para que qualquer fase da query ache uma
     variante proxima.
"""
import argparse
import json
import sys
from pathlib import Path

import librosa
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools/dashboard"))
import dsp  # noqa: E402

P = json.loads((ROOT / "params.json").read_text())
MID = P["music_id"]
LEQUE, DT_MIN, DT_MAX = MID["leque"], MID["dt_min"], MID["dt_max"]
N_FASES, DESLOC = MID["n_fases"], MID["deslocamento_fase"]
TRECHO_S = MID["trecho_s"]

FPS = dsp.SR / dsp.HOP


# ----------------------------------------------------------------- hash
def faz_hash(f1: int, f2: int, dt: int) -> int:
    """21 bits: f1(8) | f2(8) | dt(5). Tem que casar com o song_match.c."""
    return ((f1 & 0xFF) << 13) | ((f2 & 0xFF) << 5) | (dt & 0x1F)


def picos_do_sinal(y: np.ndarray) -> list[tuple[int, int]]:
    """Lista de (frame, banda), na mesma ordem que o device produziria."""
    saida = []
    for i, ini in enumerate(range(0, len(y) - dsp.N + 1, dsp.HOP)):
        fp = dsp.fp_bands(dsp.magnitude(y[ini:ini + dsp.N]))
        for b in dsp.peaks(fp):
            saida.append((i, b))
    return saida


def hashes(picos: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Pares (hash, tempo da ancora) a partir da constellation map."""
    saida = []
    for i, (t1, f1) in enumerate(picos):
        alvos = 0
        for t2, f2 in picos[i + 1:]:
            dt = t2 - t1
            if dt < DT_MIN:
                continue
            if dt > DT_MAX or alvos >= LEQUE:
                break
            saida.append((faz_hash(f1, f2, dt), t1))
            alvos += 1
    return saida


# ----------------------------------------------------------------- audio
def carrega(caminho: Path) -> np.ndarray:
    """Mono, 16 kHz — o mesmo que o INMP441 entrega."""
    y, _ = librosa.load(str(caminho), sr=dsp.SR, mono=True)
    return y.astype(np.float32)


def melhor_trecho(y: np.ndarray, segundos: float = 0) -> np.ndarray:
    """Janela de maior energia, que quase sempre cai no refrao.

    Busca em passos de 1 s: precisao de subsegundo nao muda nada aqui e
    deixaria a busca 16x mais lenta.
    """
    segundos = segundos or TRECHO_S
    if segundos <= 0:
        return y                      # 0 = faixa inteira
    n = int(segundos * dsp.SR)
    if len(y) <= n:
        return y
    passo = dsp.SR
    energia = np.cumsum(np.concatenate([[0.0], (y.astype(np.float64)) ** 2]))
    melhor, melhor_e = 0, -1.0
    for ini in range(0, len(y) - n + 1, passo):
        e = energia[ini + n] - energia[ini]
        if e > melhor_e:
            melhor, melhor_e = ini, e
    return y[melhor:melhor + n]


def impressao(y: np.ndarray, todas_as_fases: bool = True) -> list[tuple[int, int]]:
    """Hashes do trecho. Com todas_as_fases, repete deslocando o inicio."""
    fases = range(N_FASES) if todas_as_fases else [0]
    saida = []
    for f in fases:
        desl = f * DESLOC
        if desl >= len(y):
            break
        saida += hashes(picos_do_sinal(y[desl:]))
    return saida


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("arquivo")
    ap.add_argument("--fases", action="store_true", help="incluir todas as fases")
    args = ap.parse_args()

    y = carrega(Path(args.arquivo))
    if TRECHO_S > 0:
        y = melhor_trecho(y)
    pk = picos_do_sinal(y)
    hs = impressao(y, args.fases)
    frames = len(y) // dsp.HOP

    print(f"{Path(args.arquivo).name}")
    print(f"  trecho:  {len(y)/dsp.SR:.1f} s · {frames} frames")
    print(f"  picos:   {len(pk)} ({len(pk)/max(frames,1):.2f} por frame)")
    print(f"  hashes:  {len(hs)} ({'todas as fases' if args.fases else '1 fase'})")
    print(f"  distintos: {len(set(h for h, _ in hs))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
