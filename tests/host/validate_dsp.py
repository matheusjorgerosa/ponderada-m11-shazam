#!/usr/bin/env python3
"""Compara o features.c do firmware contra librosa/scipy.

Compila firmware/src/features.c no PC (stubs em tests/host/stubs/ cobrem o que
e do ESP32, com uma DFT ingenua no lugar da FFT do esp-dsp), roda sinais
sinteticos pelos dois caminhos e confere que batem.

Valida o codigo NOSSO — magnitude, centroide, filterbank mel e DCT. Nao valida
a chamada ao esp-dsp; so hardware faz isso.

    .venv/bin/python tests/host/validate_dsp.py
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import librosa
import numpy as np
from scipy.fft import dct
from scipy.signal import get_window

ROOT = Path(__file__).resolve().parents[2]
P = json.loads((ROOT / "params.json").read_text())

SR, N = P["sample_rate"], P["frame_size"]
N_MEL, N_MFCC = P["n_mel"], P["n_mfcc"]
FMIN, FMAX = P["fmin"], P["fmax"]


def compila() -> Path:
    out = Path(tempfile.mkdtemp()) / "run_features"
    cmd = [
        "gcc", "-O2", "-std=gnu11", "-Wall",
        "-I", str(ROOT / "tests/host/stubs"),
        "-I", str(ROOT / "firmware/include"),
        "-o", str(out),
        str(ROOT / "tests/host/run_features.c"),
        str(ROOT / "firmware/src/features.c"),
        "-lm",
    ]
    subprocess.run(cmd, check=True)
    return out


def features_c(binario: Path, x: np.ndarray) -> np.ndarray:
    entrada = "\n".join(f"{v:.9g}" for v in x)
    r = subprocess.run([str(binario)], input=entrada, capture_output=True,
                       text=True, check=True)
    return np.array([float(v) for v in r.stdout.strip().split(",")])


def features_py(x: np.ndarray) -> np.ndarray:
    """Referencia independente. Cada convencao aqui espelha um comentario do
    features.c — se uma delas divergir, o teste acusa."""
    rms = float(np.sqrt(np.mean(x ** 2)))

    # Hann PERIODICA (fftbins=True), nao a simetrica do np.hanning.
    win = get_window("hann", N, fftbins=True)
    mag = np.abs(np.fft.rfft(x * win))

    freqs = np.fft.rfftfreq(N, 1.0 / SR)
    den = mag.sum()
    centroid = float((freqs * mag).sum() / den) if den > 1e-12 else 0.0

    # htk=True => formula 2595*log10(1+f/700); norm=None => triangulos com pico 1.
    fb = librosa.filters.mel(sr=SR, n_fft=N, n_mels=N_MEL, fmin=FMIN, fmax=FMAX,
                             htk=True, norm=None)
    # Espectro de POTENCIA e log NATURAL.
    mel_e = np.log(fb @ (mag ** 2) + 1e-10)
    # DCT-II ortonormal.
    mfcc = dct(mel_e, type=2, norm="ortho")[:N_MFCC]

    return np.concatenate([[rms, centroid], mfcc])


def sinais():
    """Tom puro deixa quase toda banda mel no piso de 1e-10, onde o log
    amplifica ruido numerico de float32 a ponto de MFCC nenhum ser
    reprodutivel. Nenhum microfone entrega isso — sempre ha piso de ruido —
    entao a suite tem as duas familias, e a comparacao e feita relativa ao
    RMS do vetor, nao elemento a elemento."""
    t = np.arange(N) / SR
    rng = np.random.default_rng(42)
    ruido = lambda amp: amp * rng.standard_normal(N)

    yield "silencio", np.zeros(N)
    yield "senoide 1 kHz", 0.5 * np.sin(2 * np.pi * 1000 * t)
    yield "senoide 300 Hz (voz grave)", 0.5 * np.sin(2 * np.pi * 300 * t)
    yield "senoide 4 kHz (assobio)", 0.5 * np.sin(2 * np.pi * 4000 * t)
    yield "ruido branco", 0.2 * rng.standard_normal(N)
    yield "chirp 200->6000 Hz", 0.4 * np.sin(2 * np.pi * (200 + 2900 * t / t[-1]) * t)
    yield "dois tons 500+3000", 0.3 * np.sin(2 * np.pi * 500 * t) + 0.3 * np.sin(2 * np.pi * 3000 * t)
    yield "dc + tom", 0.1 + 0.3 * np.sin(2 * np.pi * 1500 * t)
    # Realistas: tom sobre piso de ruido, que e o que o INMP441 entrega.
    yield "300 Hz + piso -60 dB", 0.5 * np.sin(2 * np.pi * 300 * t) + ruido(1e-3)
    yield "4 kHz + piso -60 dB", 0.5 * np.sin(2 * np.pi * 4000 * t) + ruido(1e-3)
    yield "fala sintetica + piso", sum(0.3 / k * np.sin(2 * np.pi * 180 * k * t)
                                       for k in range(1, 12)) + ruido(1e-3)


NOMES = ["rms", "centroid"] + [f"mfcc{i}" for i in range(N_MFCC)]

# Erro maximo aceito, em fracao do RMS do vetor de features.
TOL = 1e-3


def bandas_no_piso(x: np.ndarray) -> int:
    """Quantos filtros mel ficaram grudados em log(1e-10)."""
    win = get_window("hann", N, fftbins=True)
    mag = np.abs(np.fft.rfft(x * win))
    fb = librosa.filters.mel(sr=SR, n_fft=N, n_mels=N_MEL, fmin=FMIN, fmax=FMAX,
                             htk=True, norm=None)
    return int(((fb @ (mag ** 2)) < 1e-10).sum())


def main() -> int:
    binario = compila()
    falhas = 0
    centroides = {}

    print(f"{'sinal':<28} {'pior feature':<10} {'C':>13} {'py':>13} "
          f"{'erro/rms':>10} {'piso':>5}")
    print("-" * 86)

    for nome, x in sinais():
        c, py = features_c(binario, x), features_py(x)

        # Escala pelo RMS do vetor: o autoencoder do Batch 6 consome o vetor
        # inteiro, entao o que importa e o erro contra a magnitude tipica do
        # vetor, nao contra um coeficiente que por acaso caiu perto de zero.
        rms_vec = max(float(np.sqrt(np.mean(py ** 2))), 1e-6)
        erro = np.abs(c - py) / rms_vec
        pior = int(np.argmax(erro))
        centroides[nome] = c[1]

        ok = erro[pior] < TOL
        falhas += not ok
        print(f"{nome:<28} {NOMES[pior]:<10} {c[pior]:>13.6f} {py[pior]:>13.6f} "
              f"{erro[pior]:>10.2e} {bandas_no_piso(x):>3}/{N_MEL}"
              f"{'' if ok else '   <-- FALHOU'}")

    print()
    print("Criterio de sucesso do Batch 3 — o centroide tem que reagir ao timbre:")
    grave, agudo = centroides["senoide 300 Hz (voz grave)"], centroides["senoide 4 kHz (assobio)"]
    print(f"  voz grave (300 Hz)  -> centroide {grave:8.1f} Hz")
    print(f"  assobio   (4000 Hz) -> centroide {agudo:8.1f} Hz")
    if agudo <= grave * 5:
        print("  <-- FALHOU: o agudo nao empurrou o centroide pra cima")
        falhas += 1
    else:
        print(f"  ok: {agudo / grave:.1f}x mais alto")

    print()
    print("FALHOU" if falhas else "PASSOU: features.c concorda com librosa/scipy")
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
