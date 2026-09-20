#!/usr/bin/env python3
"""Compara o peak picking do features.c contra o do dsp.py.

O peak picking e todo aritmetica inteira — soma, divisao e comparacao em
uint8/uint32 — justamente para que os dois lados deem o MESMO resultado bit a
bit. Por isso este teste exige igualdade exata, sem tolerancia.

Se algum dia alguem trocar o limiar por media movel, este teste quebra na hora:
media movel tem memoria infinita e o estado do arquivo nunca bate com o estado
do stream ao vivo.

    .venv/bin/python tests/host/validate_peaks.py
"""
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools/dashboard"))
import dsp  # noqa: E402


def compila() -> Path:
    out = Path(tempfile.mkdtemp()) / "run_peaks"
    subprocess.run([
        "gcc", "-O2", "-std=gnu11", "-Wall",
        "-I", str(ROOT / "tests/host/stubs"),
        "-I", str(ROOT / "firmware/include"),
        "-o", str(out),
        str(ROOT / "tests/host/run_peaks.c"),
        str(ROOT / "firmware/src/features.c"),
        "-lm",
    ], check=True)
    return out


def sinais() -> list[tuple[str, np.ndarray]]:
    """Frames variados; musica de verdade e tonal, entao os casos tonais pesam."""
    rng = np.random.default_rng(11)
    t = np.arange(dsp.N) / dsp.SR
    ruido = lambda a: a * rng.standard_normal(dsp.N)

    def acorde(f0, harm=4, amp=0.25):
        return sum(amp / k * np.sin(2 * np.pi * f0 * k * t) for k in range(1, harm + 1))

    casos = [
        ("silencio", np.zeros(dsp.N)),
        ("ruido branco", ruido(0.05)),
        ("tom 440", 0.3 * np.sin(2 * np.pi * 440 * t)),
        ("acorde La", acorde(440)),
        ("acorde Mi grave", acorde(165, 6)),
        ("dois acordes", acorde(220, 5) + acorde(330, 5)),
        ("agudo isolado", 0.3 * np.sin(2 * np.pi * 6000 * t) + ruido(0.002)),
        ("banda larga + tom", ruido(0.03) + 0.2 * np.sin(2 * np.pi * 1500 * t)),
    ]
    # Trechos de "musica" sintetica: progressao com ruido, que e o caso real.
    for i, f0 in enumerate([131, 165, 196, 247, 294]):
        casos.append((f"progressao {i}", acorde(f0, 6) + ruido(0.004)))
    return casos


def main() -> int:
    binario = compila()
    casos = sinais()

    entrada = "\n".join("\n".join(f"{v:.9g}" for v in x) for _, x in casos)
    r = subprocess.run([str(binario)], input=entrada, capture_output=True,
                       text=True, check=True)
    linhas = r.stdout.split("\n")

    print(f"{'sinal':<20}{'C':<26}{'python':<26}")
    print("-" * 72)
    falhas = 0
    for i, (nome, x) in enumerate(casos):
        em_c = [int(v) for v in linhas[i].split(",") if v]
        em_py = dsp.peaks(dsp.fp_bands(dsp.magnitude(x)))
        ok = em_c == em_py
        falhas += not ok
        print(f"{nome:<20}{str(em_c):<26}{str(em_py):<26}{'' if ok else 'DIVERGIU'}")

    n_picos = [len(l.split(",")) if l else 0 for l in linhas[:len(casos)]]
    print(f"\nmedia de picos por frame: {np.mean(n_picos):.2f} "
          f"(o dimensionamento do banco assume ~3)")
    print("\nPASSOU: peak picking identico em C e Python" if not falhas else "\nFALHOU")
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
