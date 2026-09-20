#!/usr/bin/env python3
"""Pipeline de DSP em Python, espelho do firmware/src/features.c.

Le o params.json — nenhum numero e duplicado. As quatro convencoes abaixo sao
as que o C fixou; divergir em qualquer uma faz o espectrograma do arquivo nao
bater com o do microfone, e voce perde horas achando que e o hardware:

  1. Janela de Hann PERIODICA (fftbins=True), nao a simetrica.
  2. Filterbank mel na escala HTK (2595*log10), triangulos sem normalizacao.
  3. Energia mel sobre o espectro de POTENCIA, com log NATURAL.
  4. DCT-II ortonormal.

tests/host/validate_dsp.py e quem garante que os dois lados continuam iguais.
"""
import json
from pathlib import Path

import librosa
import numpy as np
from scipy.fft import dct
from scipy.signal import get_window

ROOT = Path(__file__).resolve().parents[2]
P = json.loads((ROOT / "params.json").read_text())

SR = P["sample_rate"]
N = P["frame_size"]
HOP = P["hop_size"]
N_MEL = P["n_mel"]
N_MFCC = P["n_mfcc"]
FMIN = P["fmin"]
FMAX = P["fmax"]
N_BANDS = P["n_bands"]
MID = P["music_id"]
N_BANDS_FP = MID["n_bands_fp"]
N_SUPER = MID["n_super"]
MARGEM_U8 = MID["margem_u8"]
DB_MIN = P["stream"]["db_min"]
DB_MAX = P["stream"]["db_max"]

_WIN = get_window("hann", N, fftbins=True)
_MEL_FB = librosa.filters.mel(sr=SR, n_fft=N, n_mels=N_MEL, fmin=FMIN, fmax=FMAX,
                              htk=True, norm=None)

# Ganho coerente da Hann: uma senoide de amplitude A vira um pico de
# A/2 * sum(hann) na FFT. Dividir por isso faz o dB das bandas virar dBFS.
# Vale so pro espectrograma — os MFCCs usam a magnitude crua, como o librosa.
_BAND_SCALE = 2.0 / _WIN.sum()

# Bordas das 64 bandas log do dashboard, em indice de bin — mesma conta do
# features_init() em C, inclusive o truncamento pra int.
_LG = np.log10([FMIN, FMAX])


def _bordas(n_bandas: int) -> np.ndarray:
    """Mesma conta do features_init() em C, inclusive o truncamento pra int."""
    return np.clip((10 ** np.linspace(_LG[0], _LG[1], n_bandas + 1) * N / SR)
                   .astype(int), 0, N // 2)


_BAND_EDGES = _bordas(N_BANDS)
_FP_EDGES = _bordas(N_BANDS_FP)


def magnitude(frame: np.ndarray) -> np.ndarray:
    """Magnitude spectrum de um frame de N amostras. N//2+1 bins."""
    return np.abs(np.fft.rfft(frame * _WIN))


def features(frame: np.ndarray) -> np.ndarray:
    """As 15 features: [rms, centroid, mfcc0..mfcc12]."""
    rms = float(np.sqrt(np.mean(frame ** 2)))
    mag = magnitude(frame)

    freqs = np.fft.rfftfreq(N, 1.0 / SR)
    den = mag.sum()
    centroid = float((freqs * mag).sum() / den) if den > 1e-12 else 0.0

    mel_e = np.log(_MEL_FB @ (mag ** 2) + 1e-10)
    mfcc = dct(mel_e, type=2, norm="ortho")[:N_MFCC]

    return np.concatenate([[rms, centroid], mfcc])


def _comprime(mag: np.ndarray, bordas: np.ndarray, n_bandas: int) -> np.ndarray:
    """Comprime o espectro em n_bandas log, dB escalado em 0..255.

    MAXIMO da banda, nao media — igual ao C. Nas bandas graves o espaco log e
    mais estreito que um bin, e a media achataria tom puro contra o piso.
    """
    out = np.empty(n_bandas, dtype=np.uint8)
    for b in range(n_bandas):
        k0 = bordas[b]
        k1 = max(bordas[b + 1], k0 + 1)
        pico = mag[k0:min(k1, len(mag))].max(initial=0.0)
        db = 20.0 * np.log10(pico * _BAND_SCALE + 1e-9)
        u = (db - DB_MIN) / (DB_MAX - DB_MIN) * 255.0
        out[b] = int(np.clip(u, 0, 255))
    return out


def bands(mag: np.ndarray) -> np.ndarray:
    """As 64 bandas do dashboard."""
    return _comprime(mag, _BAND_EDGES, N_BANDS)


def fp_bands(mag: np.ndarray) -> np.ndarray:
    """As N_BANDS_FP bandas de resolucao fina que o hashing usa."""
    return _comprime(mag, _FP_EDGES, N_BANDS_FP)


def peaks(fp: np.ndarray) -> list[int]:
    """Pico de cada super-banda que passe da media do frame + margem.

    Espelha features_peaks() do C, em aritmetica INTEIRA: soma, divisao e
    comparacao inteiras dao resultado identico bit a bit nos dois lados. Por
    isso o validate_peaks.py testa igualdade exata, sem tolerancia.

    Limiar sem estado de proposito — media movel teria memoria infinita e
    jamais concordaria entre um arquivo e o stream ao vivo.
    """
    limiar = int(fp.astype(np.uint32).sum()) // N_BANDS_FP + MARGEM_U8
    out = []
    for g in range(N_SUPER):
        b0 = g * N_BANDS_FP // N_SUPER
        b1 = (g + 1) * N_BANDS_FP // N_SUPER
        melhor = b0 + int(np.argmax(fp[b0:b1]))   # empate fica com o menor
        if int(fp[melhor]) > limiar:
            out.append(melhor)
    return out


def band_freqs() -> np.ndarray:
    """Frequencia central de cada banda, pro eixo Y do espectrograma."""
    edges = 10 ** np.linspace(_LG[0], _LG[1], N_BANDS + 1)
    return np.sqrt(edges[:-1] * edges[1:])


def spectrogram(path: str | Path) -> dict:
    """Carrega um arquivo de audio e devolve o espectrograma nas mesmas 64
    bandas que o ESP32 emite — e o que permite comparar os dois lado a lado."""
    y, _ = librosa.load(str(path), sr=SR, mono=True)

    frames = []
    scores = []
    for i in range(0, max(len(y) - N + 1, 0), HOP):
        frame = y[i:i + N]
        mag = magnitude(frame)
        frames.append(bands(mag).tolist())
        scores.append(float(np.sqrt(np.mean(frame ** 2))))

    return {
        "sample_rate": SR,
        "frame_ms": 1000.0 * N / SR,
        "hop_ms": 1000.0 * HOP / SR,
        "duration_s": len(y) / SR,
        "band_freqs": band_freqs().round(1).tolist(),
        "frames": frames,
        "rms": scores,
    }
