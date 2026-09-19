#!/usr/bin/env python3
"""Gera 10 'musicas' sinteticas distintas para exercitar a Fase 2 sem depender
de arquivos com direitos autorais.

    .venv/bin/python music_id/gera_sinteticas.py --saida /tmp/musicas

Cada faixa tem tonalidade, progressao, qualidade de acorde, escala melodica,
andamento e timbre proprios — a primeira versao repetia a mesma triade em
todas, o que inflava artificialmente a colisao de hash entre musicas e dava
uma margem de casamento pessimista.

Nao substitui musica real: loops sinteticos tem vocabulario espectral muito
menor que uma gravacao com bateria, voz e reverb. Serve para provar que o
pipeline funciona de ponta a ponta, nao para medir margem.
"""
import argparse
from pathlib import Path

import numpy as np
import soundfile as sf

SR = 22050
NOTA = lambda n: 440.0 * 2 ** ((n - 69) / 12)

PROGS = [[0,5,7,5],[0,3,5,7],[0,7,9,5],[0,-2,3,5],[0,4,7,4],
         [0,2,4,7],[0,5,3,7],[0,-3,4,5],[0,7,5,2],[0,3,7,10]]
TONS = [48, 50, 52, 53, 55, 57, 59, 45, 47, 51]
BPM = [92, 120, 76, 140, 104, 88, 132, 68, 112, 96]
ACORDES = [(0,4,7),(0,3,7),(0,5,7),(0,4,7,10),(0,3,7,10),
           (0,4,7,11),(0,3,6),(0,4,8),(0,2,7),(0,5,10)]
ESCALAS = [[0,2,4,5,7,9,11],[0,2,3,5,7,8,10],[0,2,4,7,9],[0,1,5,7,8],
           [0,3,5,6,7,10],[0,2,4,6,7,9,11],[0,2,3,7,8],[0,4,5,7,11],
           [0,1,3,5,7,8,10],[0,2,5,7,10]]


def voz(f, dur, pesos, decai):
    t = np.arange(int(dur * SR)) / SR
    env = np.exp(-t * decai)
    return sum(w * np.sin(2 * np.pi * f * (k + 1) * t)
               for k, w in enumerate(pesos)) * env


def faixa(i: int, segundos: float = 70.0) -> np.ndarray:
    rng = np.random.default_rng(100 + i)
    prog, tonica, bpm = PROGS[i], TONS[i], BPM[i]
    acorde, escala = ACORDES[i], ESCALAS[i]
    pesos = np.array([1.0] + list(rng.uniform(0.15, 0.85, 5)))
    pesos /= pesos.sum()

    compasso = 240.0 / bpm
    total = int(segundos * SR)
    y = np.zeros(total)
    pos, c = 0, 0
    while pos < total:
        grau = prog[c % len(prog)]
        for semi in acorde:
            s = voz(NOTA(tonica + grau + semi), compasso, pesos, 1.3)
            n = min(len(s), total - pos)
            y[pos:pos + n] += 0.16 * s[:n]
        for j in range(8):
            nota = (tonica + 12 + grau + int(rng.choice(escala))
                    + 12 * int(rng.integers(0, 2)))
            off = pos + int(j * compasso / 8 * SR)
            s = voz(NOTA(nota), compasso / 6, pesos, 4.0)
            n = min(len(s), total - off)
            if n > 0:
                y[off:off + n] += 0.12 * s[:n]
        for j in range(4):
            off = pos + int(j * compasso / 4 * SR)
            n = min(int(0.05 * SR), total - off)
            if n > 0:
                dec = SR * (0.008 + 0.012 * (i % 3))
                y[off:off + n] += (0.09 * rng.standard_normal(n)
                                   * np.exp(-np.arange(n) / dec))
        pos += int(compasso * SR)
        c += 1

    # "refrao" mais forte no meio, pra o recorte por energia ter o que achar
    y[int(0.43 * total):int(0.89 * total)] *= 1.7
    return (y / max(abs(y).max(), 1e-9) * 0.8).astype(np.float32)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--saida", default="/tmp/musicas_sinteticas")
    ap.add_argument("--n", type=int, default=10)
    args = ap.parse_args()

    destino = Path(args.saida)
    destino.mkdir(parents=True, exist_ok=True)
    for i in range(args.n):
        nome = destino / f"{i+1:02d}-sintetica-{i+1}.wav"
        sf.write(nome, faixa(i), SR)
        print(f"  {nome.name}  tom={TONS[i]} bpm={BPM[i]} acorde={ACORDES[i]}")
    print(f"\n{args.n} faixas em {destino}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
