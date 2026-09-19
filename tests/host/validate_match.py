#!/usr/bin/env python3
"""Compara o casamento do song_match.c com o do build_db.py.

Gera consultas ruidosas a partir das musicas, extrai os picos em Python e
alimenta os dois caminhos com EXATAMENTE a mesma sequencia de picos. O que se
testa aqui e so a votacao: hashing, busca binaria e histograma. O peak picking
em si ja tem o seu proprio teste (validate_peaks.py).

    .venv/bin/python tests/host/validate_match.py --dir /tmp/musicas
"""
import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "music_id"))
sys.path.insert(0, str(ROOT / "tools/dashboard"))
import dsp                    # noqa: E402
import build_db as bd         # noqa: E402
import fingerprint as fp      # noqa: E402


def compila() -> Path:
    out = Path(tempfile.mkdtemp()) / "run_match"
    subprocess.run([
        "gcc", "-O2", "-std=gnu11", "-Wall",
        "-I", str(ROOT / "tests/host/stubs"),
        "-I", str(ROOT / "firmware/include"),
        "-o", str(out),
        str(ROOT / "tests/host/run_match.c"),
        str(ROOT / "firmware/src/song_match.c"),
        str(ROOT / "firmware/src/song_db.c"),
        "-lm",
    ], check=True)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="music_id/songs")
    ap.add_argument("--snr", type=float, default=-10.0)
    args = ap.parse_args()

    pasta = Path(args.dir)
    if not pasta.is_absolute():
        pasta = ROOT / pasta
    arquivos = sorted(p for p in pasta.iterdir()
                      if p.suffix.lower() in {".wav", ".mp3", ".flac", ".m4a", ".ogg"})
    if not arquivos:
        sys.exit(f"nenhum audio em {pasta}")

    # O banco que o C usa e o song_db.c gerado; carrego o mesmo em Python.
    import re
    txt = (ROOT / "firmware/src/song_db.c").read_text()
    arr = np.array([int(v, 16) for v in re.findall(r"0x([0-9a-f]{16})ULL", txt)],
                   dtype=np.uint64)
    nomes = [bd.titulo(a.stem) for a in arquivos]
    print(f"banco: {len(arr):,} entradas · {len(arquivos)} musicas\n")

    binario = compila()
    rng = np.random.default_rng(7)
    dur = bd.MID["janela_s"]
    n = int(dur * dsp.SR)

    print(f"{'musica':<20}{'C':<20}{'python':<20}{'igual':>7}")
    print("-" * 67)
    falhas = acertos = 0

    for sid, arq in enumerate(arquivos):
        y = fp.melhor_trecho(fp.carrega(arq))
        ini = int(rng.integers(0, max(len(y) - n - dsp.N, 1))) + int(rng.integers(0, dsp.HOP))
        tr = y[ini:ini + n]
        pot = np.mean(tr ** 2)
        tr = (tr + rng.normal(0, np.sqrt(pot / 10 ** (args.snr / 10)),
                              len(tr))).astype(np.float32)

        # Picos uma vez so, usados pelos dois lados.
        picos = fp.picos_do_sinal(tr)
        por_frame: dict[int, list[int]] = {}
        for t, b in picos:
            por_frame.setdefault(t, []).append(b)
        n_frames = max(por_frame) + 1 if por_frame else 0
        entrada = "\n".join(",".join(str(b) for b in por_frame.get(t, []))
                            for t in range(n_frames))

        r = subprocess.run([str(binario)], input=entrada + "\n",
                           capture_output=True, text=True, check=True)
        c_match, c_votos = -1, 0
        for l in r.stdout.strip().split("\n"):
            m, v = l.split(",")
            if int(m) >= 0:
                c_match, c_votos = int(m), int(v)
                break                      # o C dispara no primeiro casamento

        py_match, py_votos, _ = bd.casa(arr, fp.hashes(picos))

        igual = c_match == py_match
        falhas += not igual
        acertos += c_match == sid
        c_nome = nomes[c_match] if c_match >= 0 else "(nenhum)"
        print(f"{nomes[sid]:<20}{c_nome:<20}{nomes[py_match]:<20}"
              f"{'sim' if igual else 'NAO':>7}")

    print(f"\n{acertos}/{len(arquivos)} identificadas corretamente pelo C")
    print("PASSOU: song_match.c concorda com o build_db.py" if not falhas
          else "FALHOU: as duas implementacoes divergem")
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
