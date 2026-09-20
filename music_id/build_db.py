#!/usr/bin/env python3
"""Monta o banco de fingerprints e emite o binario que vai embutido no firmware.

    .venv/bin/python music_id/build_db.py                 # monta de music_id/songs/
    .venv/bin/python music_id/build_db.py --testar        # valida sem device

Formato de cada entrada, uint64 little-endian:
    bits 63..32  hash de 21 bits (f1 8 | f2 8 | dt 5)
    bits 15..12  songID (0..15)
    bits 11..0   tempo da ancora, em frames

O array sai ordenado, entao o device faz busca binaria direto sobre ele.
Guardar o hash na metade alta faz a ordenacao por uint64 ja ordenar por hash.
"""
import argparse
import json
import struct
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "music_id"))
sys.path.insert(0, str(ROOT / "tools/dashboard"))
import dsp           # noqa: E402
import fingerprint as fpmod   # noqa: E402

P = json.loads((ROOT / "params.json").read_text())
MID = P["music_id"]
MAX_MUSICAS = MID["max_musicas"]
CAP = MID["max_por_hash_musica"]
JANELA_FRAMES = int(MID["janela_s"] * dsp.SR / dsp.HOP)
TRECHO_FRAMES = int(MID["trecho_s"] * dsp.SR / dsp.HOP)
N_OFFSETS = TRECHO_FRAMES + JANELA_FRAMES + 1
VOTOS_MIN = MID["votos_min"]

DB_BIN = ROOT / "firmware/song_db.bin"
LISTA = ROOT / "music_id/songs.json"

# factory de 2 MB (firmware/partitions.csv) menos o que o app ja ocupa.
LIMITE_BYTES = 2 * 1024 * 1024 - 400 * 1024


def entrada(h: int, song_id: int, t: int) -> int:
    return (h << 32) | ((song_id & 0xF) << 12) | (t & 0xFFF)


def poda(hs: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Mantem no maximo CAP entradas por hash, espalhadas no tempo.

    Sem isso um punhado de hashes populares domina o banco: no teste com
    musica sintetica, o mais comum aparecia 449 vezes numa unica musica, e um
    acerto nele sozinho despejava votos suficientes para o segundo colocado
    chegar perto do primeiro. Espalhar no tempo (em vez de pegar os primeiros)
    preserva a cobertura do trecho inteiro.
    """
    from collections import defaultdict
    por_hash: dict[int, list[int]] = defaultdict(list)
    for h, t in hs:
        por_hash[h].append(t)

    saida = []
    for h, tempos in por_hash.items():
        tempos.sort()
        if len(tempos) <= CAP:
            saida += [(h, t) for t in tempos]
        else:
            idx = np.linspace(0, len(tempos) - 1, CAP).round().astype(int)
            saida += [(h, tempos[i]) for i in sorted(set(idx))]
    return saida


def monta(pasta: Path) -> tuple[np.ndarray, list[str]]:
    arquivos = sorted(p for p in pasta.iterdir()
                      if p.suffix.lower() in {".wav", ".mp3", ".flac", ".m4a", ".ogg"})
    if not arquivos:
        sys.exit(f"nenhum audio em {pasta}")
    if len(arquivos) > MAX_MUSICAS:
        sys.exit(f"{len(arquivos)} arquivos, mas max_musicas={MAX_MUSICAS} "
                 f"(songID tem 4 bits)")

    tudo, nomes = [], []
    for sid, arq in enumerate(arquivos):
        y = fpmod.melhor_trecho(fpmod.carrega(arq))
        hs = fpmod.impressao(y, todas_as_fases=True)
        mantidos = poda(hs)
        tudo += [entrada(h, sid, t) for h, t in mantidos]
        nomes.append(arq.stem)
        print(f"  [{sid}] {arq.stem:<26} {len(hs):>6} hashes -> "
              f"{len(mantidos):>6} apos poda")

    arr = np.array(sorted(tudo), dtype=np.uint64)
    return arr, nomes


def grava(arr: np.ndarray, nomes: list[str]) -> None:
    tamanho = arr.nbytes
    print(f"\n{len(arr):,} entradas · {tamanho/1024:.0f} KB "
          f"({tamanho/LIMITE_BYTES:.0%} do que sobra na particao)")
    if tamanho > LIMITE_BYTES:
        sys.exit(f"ESTOUROU: {tamanho/1024:.0f} KB > {LIMITE_BYTES/1024:.0f} KB. "
                 f"Reduza music_id.leque ou music_id.n_fases no params.json.")

    DB_BIN.write_bytes(arr.tobytes())
    LISTA.write_text(json.dumps({"musicas": nomes}, indent=2, ensure_ascii=False))
    print(f"gerado: {DB_BIN.relative_to(ROOT)}")
    print(f"gerado: {LISTA.relative_to(ROOT)}")


# ------------------------------------------------------------- consulta
def casa(arr: np.ndarray, hs: list[tuple[int, int]]) -> tuple[int, int, int]:
    """Votacao por offset. Devolve (songID, votos, offset) do melhor bin.

    Mesma logica do song_match.c: para cada hash da query, busca binaria no
    banco e voto em (musica, t_banco - t_query). Um match verdadeiro alinha
    todos os pares no mesmo offset; colisao espalha uniforme.
    """
    hist = np.zeros((MAX_MUSICAS, N_OFFSETS), dtype=np.int32)
    chaves = arr >> np.uint64(32)

    for h, t_query in hs:
        i = int(np.searchsorted(chaves, np.uint64(h), side="left"))
        while i < len(arr) and int(chaves[i]) == h:
            payload = int(arr[i]) & 0xFFFF
            sid, t_db = payload >> 12, payload & 0xFFF
            off = t_db - t_query + JANELA_FRAMES
            if 0 <= off < N_OFFSETS:
                hist[sid, off] += 1
            i += 1

    sid, off = np.unravel_index(int(hist.argmax()), hist.shape)
    melhor = int(hist[sid, off])
    # Segundo colocado entre as OUTRAS musicas: e essa margem que diz se o
    # match e solido ou sorte. Dentro da mesma musica, bins vizinhos votam
    # junto e nao contam como concorrencia.
    outros = np.delete(hist, sid, axis=0)
    segundo = int(outros.max()) if outros.size else 0
    return int(sid), melhor, segundo


def testar(arr: np.ndarray, nomes: list[str], pasta: Path, snr_db: float) -> int:
    """Simula gravacoes ruidosas e confere se o banco identifica cada musica."""
    arquivos = sorted(p for p in pasta.iterdir()
                      if p.suffix.lower() in {".wav", ".mp3", ".flac", ".m4a", ".ogg"})
    rng = np.random.default_rng(7)
    dur = MID["janela_s"]

    print(f"\nconsulta de {dur:g} s, ruido a {snr_db:+.0f} dB SNR, "
          f"fase e instante aleatorios\n")
    print(f"{'esperado':<26}{'obtido':<26}{'votos':>6}{'2o lugar':>8}{'margem':>9}")
    print("-" * 75)

    acertos, margens = 0, []
    for sid, arq in enumerate(arquivos):
        y = fpmod.melhor_trecho(fpmod.carrega(arq))
        n = int(dur * dsp.SR)
        # instante aleatorio e deslocamento de fase arbitrario: e assim que o
        # device pega o audio, nunca alinhado com a grade do banco.
        ini = int(rng.integers(0, max(len(y) - n - dsp.N, 1)))
        ini += int(rng.integers(0, dsp.HOP))
        trecho = y[ini:ini + n]

        pot = np.mean(trecho ** 2)
        ruido = rng.normal(0, np.sqrt(pot / (10 ** (snr_db / 10))), len(trecho))
        trecho = (trecho + ruido).astype(np.float32)

        # a query usa UMA fase so — quem tem varias e o banco
        hs = fpmod.hashes(fpmod.picos_do_sinal(trecho))
        obtido, votos, segundo = casa(arr, hs)

        ok = obtido == sid
        acertos += ok
        margens.append(votos / max(segundo, 1))
        print(f"{nomes[sid]:<26}{nomes[obtido]:<26}{votos:>6}{segundo:>8}"
              f"{votos/max(segundo,1):>8.1f}x{'' if ok else '  ERRO'}")

    print(f"\n{acertos}/{len(arquivos)} corretas · limiar de votos = {VOTOS_MIN} · "
          f"margem minima {min(margens):.1f}x")
    return 0 if acertos == len(arquivos) else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="music_id/songs")
    ap.add_argument("--testar", action="store_true")
    ap.add_argument("--snr", type=float, default=-10.0)
    args = ap.parse_args()

    pasta = Path(args.dir)
    if not pasta.is_absolute():
        pasta = ROOT / pasta

    print(f"montando de {pasta}")
    arr, nomes = monta(pasta)
    grava(arr, nomes)
    return testar(arr, nomes, pasta, args.snr) if args.testar else 0


if __name__ == "__main__":
    sys.exit(main())
