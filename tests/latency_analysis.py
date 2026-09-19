#!/usr/bin/env python3
"""Percentis de latencia por etapa, a partir do log do firmware.

    .venv/bin/python tests/latency_analysis.py captura.log
    .venv/bin/python tests/latency_analysis.py --serial --segundos 120

Le as linhas D, do firmware:
    D,<seq>,<score>,<threshold>,<anomalia>,<cap_feat_us>,<feat_det_us>,<total_us>

Cada etapa inclui a espera na fila que a precede — e ali que o gargalo
aparece, nao no calculo em si. Gera docs/latencia.png e imprime a tabela que
vai pro relatorio.
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
P = json.loads((ROOT / "params.json").read_text())
FRAME_MS = 1000.0 * P["frame_size"] / P["sample_rate"]

ETAPAS = [("captura -> features", 5),
          ("features -> deteccao", 6),
          ("ponta a ponta", 7)]


def do_serial(segundos: float) -> list[str]:
    import serial
    porta = P.get("_porta", "/dev/ttyUSB0")
    linhas, t0 = [], None
    import time
    with serial.Serial(porta, P["serial"]["baud"], timeout=1) as s:
        t0 = time.time()
        while time.time() - t0 < segundos:
            l = s.readline().decode("utf-8", "replace").strip()
            if l.startswith("D,"):
                linhas.append(l)
            restante = segundos - (time.time() - t0)
            if len(linhas) % 200 == 0 and linhas:
                print(f"\r{len(linhas)} frames · {restante:.0f}s restantes",
                      end="", flush=True)
    print()
    return linhas


def parse(linhas) -> np.ndarray:
    dados = []
    for l in linhas:
        if not l.startswith("D,"):
            continue
        p = l.split(",")
        if len(p) < 8:
            continue          # log antigo, sem as etapas separadas
        try:
            dados.append([float(p[5]), float(p[6]), float(p[7])])
        except ValueError:
            continue
    return np.array(dados)


def tabela(d: np.ndarray) -> None:
    print(f"\n{len(d)} frames · orcamento de {FRAME_MS:.0f} ms por frame\n")
    print(f"{'etapa':<24}{'p50':>9}{'p95':>9}{'p99':>9}{'max':>9}{'% do frame':>12}")
    print("-" * 72)
    for i, (nome, _) in enumerate(ETAPAS):
        c = d[:, i]
        p50, p95, p99 = np.percentile(c, [50, 95, 99])
        print(f"{nome:<24}{p50/1000:>8.2f}m{p95/1000:>8.2f}m{p99/1000:>8.2f}m"
              f"{c.max()/1000:>8.2f}m{100*p99/1000/FRAME_MS:>11.1f}%")
    print("\n(valores em ms; a coluna final e o p99 ponta a ponta sobre o "
          "orcamento do frame)")


def grafico(d: np.ndarray, destino: Path) -> None:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("matplotlib nao instalado; pulando o grafico")
        return

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 4))

    rotulos = ["cap→feat", "feat→det", "total"]
    caixas = [d[:, i] / 1000 for i in range(3)]
    try:
        ax1.boxplot(caixas, tick_labels=rotulos, showfliers=False)
    except TypeError:      # matplotlib < 3.9 chamava isso de `labels`
        ax1.boxplot(caixas, labels=rotulos, showfliers=False)
    ax1.axhline(FRAME_MS, color="crimson", ls="--", lw=1,
                label=f"orçamento do frame ({FRAME_MS:.0f} ms)")
    ax1.set_ylabel("latência (ms)")
    ax1.set_title("Distribuição por etapa")
    ax1.legend(fontsize=8)
    ax1.grid(alpha=.3)

    for i, (nome, _) in enumerate(ETAPAS):
        c = np.sort(d[:, i]) / 1000
        ax2.plot(c, np.linspace(0, 100, len(c)), label=nome)
    ax2.set_xlabel("latência (ms)")
    ax2.set_ylabel("percentil")
    ax2.set_title("Distribuição acumulada")
    ax2.legend(fontsize=8)
    ax2.grid(alpha=.3)

    fig.tight_layout()
    destino.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(destino, dpi=130)
    print(f"\ngerado: {destino.relative_to(ROOT)}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("log", nargs="?", help="arquivo de log; omita com --serial")
    ap.add_argument("--serial", action="store_true", help="le direto da serial")
    ap.add_argument("--segundos", type=float, default=120)
    ap.add_argument("--saida", default="docs/latencia.png")
    args = ap.parse_args()

    if args.serial:
        linhas = do_serial(args.segundos)
    elif args.log:
        linhas = Path(args.log).read_text(errors="replace").splitlines()
    else:
        linhas = sys.stdin.read().splitlines()

    d = parse(linhas)
    if not len(d):
        sys.exit("nenhuma linha D, com as tres etapas encontrada")

    tabela(d)
    grafico(d, ROOT / args.saida)
    return 0


if __name__ == "__main__":
    sys.exit(main())
