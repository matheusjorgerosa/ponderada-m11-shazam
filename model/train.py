#!/usr/bin/env python3
"""Treina o autoencoder de anomalia e gera os dois artefatos do device.

    .venv/bin/python model/train.py

Entra:  model/data/normal.csv   (~10 min de som normal — define o que e normal)
        model/data/anomaly.csv  (~1 min de anomalias — NAO treina, so valida)
Sai:    model/anomaly_detector.onnx        (entregavel)
        firmware/include/model_weights.h   (pesos pro C)

O modelo so ve som normal. O score e o erro de reconstrucao: o que o
autoencoder nunca viu, ele reconstroi mal, e o erro sobe.
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn

ROOT = Path(__file__).resolve().parents[1]
P = json.loads((ROOT / "params.json").read_text())
M = P["model"]
N_FEAT = 2 + P["n_mfcc"]

NOMES = ["rms", "centroid"] + [f"mfcc{i}" for i in range(P["n_mfcc"])]


class Autoencoder(nn.Module):
    """15 -> 8 -> 4 -> 8 -> 15. ReLU em tudo menos na saida, que e linear.

    A normalizacao entra no modulo como buffer, entao o .onnx exportado recebe
    as features cruas — o mesmo que o ESP32 faz. Um .onnx que exigisse o
    consumidor normalizar por fora seria uma armadilha."""

    def __init__(self, mean: np.ndarray, std: np.ndarray):
        super().__init__()
        h1, lat = M["hidden1"], M["latent"]
        self.register_buffer("mean", torch.tensor(mean, dtype=torch.float32))
        self.register_buffer("std", torch.tensor(std, dtype=torch.float32))
        self.enc1 = nn.Linear(N_FEAT, h1)
        self.enc2 = nn.Linear(h1, lat)
        self.dec1 = nn.Linear(lat, h1)
        self.dec2 = nn.Linear(h1, N_FEAT)

    def forward(self, x):
        z = (x - self.mean) / self.std
        h = torch.relu(self.enc1(z))
        h = torch.relu(self.enc2(h))
        h = torch.relu(self.dec1(h))
        recon = self.dec2(h)
        score = ((recon - z) ** 2).mean(dim=-1)
        return recon, score


def carrega(caminho: Path) -> np.ndarray:
    if not caminho.exists():
        return np.empty((0, N_FEAT), dtype=np.float32)
    dados = np.genfromtxt(caminho, delimiter=",", skip_header=1, dtype=np.float32)
    if dados.ndim == 1:
        dados = dados.reshape(1, -1)
    dados = dados[~np.isnan(dados).any(axis=1)]
    if dados.size and dados.shape[1] != N_FEAT:
        sys.exit(f"{caminho}: esperava {N_FEAT} colunas, achei {dados.shape[1]}")
    return dados


def gera_header(modelo: Autoencoder, limiar: float, destino: Path,
                origem: str, n_frames: int) -> None:
    """Pesos como const float[] em .rodata — vai pra flash, nao gasta RAM."""

    def arr(nome: str, v: np.ndarray, por_linha: int = 6) -> str:
        achatado = v.reshape(-1)
        linhas, buf = [], []
        for i, x in enumerate(achatado):
            buf.append(f"{x:+.8e}f")
            if len(buf) == por_linha or i == len(achatado) - 1:
                linhas.append("    " + ", ".join(buf))
                buf = []
        corpo = ",\n".join(linhas)
        return f"static const float {nome}[{len(achatado)}] = {{\n{corpo}\n}};\n"

    h1, lat = M["hidden1"], M["latent"]
    p = {k: v.detach().numpy() for k, v in modelo.state_dict().items()}

    from datetime import datetime
    txt = f"""/* GERADO POR model/train.py — NAO EDITE A MAO.
 *
 * Origem: {origem} · {n_frames} frames · {datetime.now():%Y-%m-%d %H:%M}
 *
 * Autoencoder {N_FEAT}->{h1}->{lat}->{h1}->{N_FEAT}, float32.
 * Pesos em [saida][entrada], linha por linha: acumule w[o*n_in + i] * x[i].
 */
#ifndef MODEL_WEIGHTS_H
#define MODEL_WEIGHTS_H

#define MODEL_N_IN   {N_FEAT}
#define MODEL_H1     {h1}
#define MODEL_LATENT {lat}

/* Erro de reconstrucao acima disto e anomalia. Percentil {M["threshold_percentile"]}
 * do conjunto normal de validacao, que o treino nunca viu. */
static const float model_threshold = {limiar:.8e}f;

{arr("model_mean", p["mean"])}
{arr("model_std", p["std"])}
{arr("w_enc1", p["enc1.weight"])}
{arr("b_enc1", p["enc1.bias"])}
{arr("w_enc2", p["enc2.weight"])}
{arr("b_enc2", p["enc2.bias"])}
{arr("w_dec1", p["dec1.weight"])}
{arr("b_dec1", p["dec1.bias"])}
{arr("w_dec2", p["dec2.weight"])}
{arr("b_dec2", p["dec2.bias"])}
#endif /* MODEL_WEIGHTS_H */
"""
    destino.write_text(txt)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--normal", default="model/data/normal.csv")
    ap.add_argument("--anomaly", default="model/data/anomaly.csv")
    ap.add_argument("--percentil", type=float, default=M["threshold_percentile"])
    args = ap.parse_args()

    torch.manual_seed(M["seed"])
    rng = np.random.default_rng(M["seed"])

    normal = carrega(ROOT / args.normal)
    anomalo = carrega(ROOT / args.anomaly)
    if len(normal) < 100:
        sys.exit(f"{args.normal}: so {len(normal)} frames. Colete mais — "
                 f"10 min dao ~9400.")

    # Split ANTES de qualquer estatistica: mean/std e threshold calculados
    # sobre dados que o treino viu dariam numeros otimistas.
    idx = rng.permutation(len(normal))
    corte = int(len(normal) * (1 - M["val_split"]))
    treino, val = normal[idx[:corte]], normal[idx[corte:]]

    mean = treino.mean(axis=0)
    std = treino.std(axis=0)
    std[std < 1e-6] = 1.0      # feature constante viraria divisao por zero

    modelo = Autoencoder(mean, std)
    otim = torch.optim.Adam(modelo.parameters(), lr=M["learning_rate"])
    perda_fn = nn.MSELoss()

    xt = torch.tensor(treino)
    xv = torch.tensor(val)
    n_lote = M["batch_size"]

    print(f"treino {len(treino)} frames · validacao {len(val)} · "
          f"anomalias {len(anomalo)}")
    print(f"{'epoca':>6} {'treino':>12} {'validacao':>12}")

    for epoca in range(M["epochs"]):
        modelo.train()
        ordem = torch.randperm(len(xt))
        acc = 0.0
        for i in range(0, len(xt), n_lote):
            lote = xt[ordem[i:i + n_lote]]
            recon, _ = modelo(lote)
            alvo = (lote - modelo.mean) / modelo.std
            perda = perda_fn(recon, alvo)
            otim.zero_grad()
            perda.backward()
            otim.step()
            acc += perda.item() * len(lote)

        if epoca % 20 == 0 or epoca == M["epochs"] - 1:
            modelo.eval()
            with torch.no_grad():
                _, sv = modelo(xv)
            print(f"{epoca:>6} {acc / len(xt):>12.6f} {sv.mean().item():>12.6f}")

    modelo.eval()
    with torch.no_grad():
        _, score_val = modelo(xv)
        score_val = score_val.numpy()
        score_ano = modelo(torch.tensor(anomalo))[1].numpy() if len(anomalo) else None

    limiar = float(np.percentile(score_val, args.percentil))

    # ---- artefatos ----
    onnx_path = ROOT / "model/anomaly_detector.onnx"
    torch.onnx.export(
        modelo, torch.zeros(1, N_FEAT),
        str(onnx_path),
        input_names=["features"], output_names=["reconstruction", "score"],
        dynamic_axes={"features": {0: "batch"}, "reconstruction": {0: "batch"},
                      "score": {0: "batch"}},
        # Pesos embutidos: o exportador novo grava um sidecar .onnx.data por
        # padrao, e um entregavel em dois arquivos se perde na entrega.
        external_data=False,
    )
    header = ROOT / "firmware/include/model_weights.h"
    gera_header(modelo, limiar, header, args.normal, len(normal))

    # ---- relatorio ----
    #
    # Duas metricas, e a que importa e a segunda.
    #
    # Por FRAME subestima a deteccao: o anomaly.csv rotula a janela inteira de
    # cada som, mas dentro do bloco de palmas a maioria dos frames e o silencio
    # entre uma palma e outra — frames que o detector acerta em NAO marcar, e
    # que a metrica conta como falha.
    #
    # Por EVENTO e o que o device faz: ele alerta quando DEBOUNCE_N frames
    # consecutivos passam do threshold, e um alerta vale pelo evento todo.
    # Janela de 1 s, que e a ordem de grandeza de uma palma ou de uma batida.
    deb = P["detector"]["debounce_n"]
    jan = max(int(round(P["sample_rate"] / P["frame_size"])), 1)   # ~1 s

    def por_evento(scores: np.ndarray) -> float:
        """Fracao das janelas em que o device teria alertado."""
        alertas = 0
        total = 0
        for i in range(0, len(scores) - jan + 1, jan):
            total += 1
            seguidos = 0
            for v in scores[i:i + jan]:
                seguidos = seguidos + 1 if v > limiar else 0
                if seguidos >= deb:
                    alertas += 1
                    break
        return alertas / max(total, 1), total

    fp_frame = float((score_val > limiar).mean())
    fp_ev, n_jan_val = por_evento(score_val)

    print()
    print(f"threshold (percentil {args.percentil:g} da validacao): {limiar:.6f}")
    print(f"debounce: {deb} frames consecutivos · janela de evento: {jan} frames (~1 s)")
    print()
    print(f"{'':<26}{'por frame':>12}{'por evento':>13}")
    print("-" * 51)
    print(f"{'falso positivo (normal)':<26}{fp_frame:>11.2%}{fp_ev:>12.2%}")

    if score_ano is not None and len(score_ano):
        tp_frame = float((score_ano > limiar).mean())
        tp_ev, n_jan_ano = por_evento(score_ano)
        print(f"{'deteccao (anomalia)':<26}{tp_frame:>11.2%}{tp_ev:>12.2%}")

        vn = int(round(n_jan_val * (1 - fp_ev)));  fp_n = n_jan_val - vn
        vp = int(round(n_jan_ano * tp_ev));        fn_n = n_jan_ano - vp
        print()
        print(f"matriz de confusao, por janela de ~1 s")
        print(f"{'':>12}{'previu normal':>16}{'previu anomalia':>18}")
        print(f"{'normal':>12}{vn:>16}{fp_n:>18}")
        print(f"{'anomalia':>12}{fn_n:>16}{vp:>18}")
        acc = (vn + vp) / (n_jan_val + n_jan_ano)
        print(f"\nacuracia por evento: {acc:.2%}  "
              f"({n_jan_val} janelas normais, {n_jan_ano} anomalas)")

        if fp_ev < 0.02 and tp_ev > 0.85:
            print("\nDENTRO DA META (falso positivo < 2%, deteccao > 85%).")
        else:
            print("\nFORA DA META. Ajuste --percentil: subir reduz falso "
                  "positivo, descer aumenta deteccao.")
        if n_jan_ano < 60:
            print(f"Ressalva: so {n_jan_ano} janelas anomalas — "
                  f"cada uma vale {100/n_jan_ano:.1f} pontos percentuais.")
    else:
        print("\nsem anomaly.csv — colete com: "
              "model/collect.py --guiado --saida model/data/anomaly.csv")

    print(f"\ngerado: {onnx_path.relative_to(ROOT)}")
    print(f"gerado: {header.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
