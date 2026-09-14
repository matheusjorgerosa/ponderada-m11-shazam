#!/usr/bin/env python3
"""Compara as 4 matmuls do detector.c contra o anomaly_detector.onnx.

Compila firmware/src/detector.c no PC e roda os mesmos frames pelos dois
caminhos. Se a inferencia em C divergir do modelo treinado, aparece aqui — e
nao na demonstracao.

    .venv/bin/python tests/host/validate_model.py
"""
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import onnxruntime as ort

ROOT = Path(__file__).resolve().parents[2]
TOL_REL = 1e-4        # float32 puro fica na casa de 1e-7


def compila() -> Path:
    out = Path(tempfile.mkdtemp()) / "run_detector"
    subprocess.run([
        "gcc", "-O2", "-std=gnu11", "-Wall",
        "-I", str(ROOT / "tests/host/stubs"),
        "-I", str(ROOT / "firmware/include"),
        "-o", str(out),
        str(ROOT / "tests/host/run_detector.c"),
        str(ROOT / "firmware/src/detector.c"),
        "-lm",
    ], check=True)
    return out


def threshold_do_header() -> float:
    txt = (ROOT / "firmware/include/model_weights.h").read_text()
    m = re.search(r"model_threshold\s*=\s*([-+0-9.eE]+)f", txt)
    if not m:
        sys.exit("model_threshold nao encontrado no model_weights.h")
    return float(m.group(1))


def csv(nome: str) -> np.ndarray:
    caminho = ROOT / "model/data" / nome
    if not caminho.exists():
        return np.empty((0, 15), dtype=np.float32)
    d = np.genfromtxt(caminho, delimiter=",", skip_header=1, dtype=np.float32)
    return d[~np.isnan(d).any(axis=1)] if d.size else d


def main() -> int:
    X = np.vstack([csv("normal.csv")[:1000], csv("anomaly.csv")[:500]])
    if not len(X):
        sys.exit("sem model/data/*.csv — rode o collect.py antes")

    binario = compila()
    entrada = "\n".join(",".join(f"{v:.9g}" for v in linha) for linha in X)
    r = subprocess.run([str(binario)], input=entrada, capture_output=True,
                       text=True, check=True)
    score_c = np.array([float(v) for v in r.stdout.split()])

    sess = ort.InferenceSession(str(ROOT / "model/anomaly_detector.onnx"))
    _, score_onnx = sess.run(None, {"features": X})

    if len(score_c) != len(score_onnx):
        sys.exit(f"o C devolveu {len(score_c)} scores, o onnx {len(score_onnx)}")

    rel = np.abs(score_c - score_onnx) / np.maximum(np.abs(score_onnx), 1e-9)
    thr = threshold_do_header()
    divergentes = int(((score_c > thr) != (score_onnx > thr)).sum())

    print(f"frames comparados:     {len(X)}")
    print(f"erro relativo maximo:  {rel.max():.2e}  (tolerancia {TOL_REL:.0e})")
    print(f"erro relativo medio:   {rel.mean():.2e}")
    print(f"threshold:             {thr:.6f}")
    print(f"decisoes divergentes:  {divergentes} de {len(X)}")

    ok = rel.max() < TOL_REL and divergentes == 0
    print("\nPASSOU: detector.c concorda com o onnx" if ok else "\nFALHOU")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
