#!/usr/bin/env python3
"""Gera firmware/include/config.h e firmware/sdkconfig.defaults a partir do params.json.

Rode sempre que mexer no params.json:
    python3 tools/gen_config.py
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
P = json.loads((ROOT / "params.json").read_text())

pins, i2s, ser, det = P["pins"], P["i2s"], P["serial"], P["detector"]
n_fft_bins = P["frame_size"] // 2 + 1
frame_ms = 1000.0 * P["frame_size"] / P["sample_rate"]

config_h = f"""/* GERADO POR tools/gen_config.py A PARTIR DE params.json — NAO EDITE A MAO. */
#ifndef CONFIG_H
#define CONFIG_H

/* ---- DSP ---- */
#define SAMPLE_RATE        {P["sample_rate"]}
#define FRAME_SIZE         {P["frame_size"]}
#define HOP_SIZE           {P["hop_size"]}
#define N_FFT_BINS         {n_fft_bins}
#define N_MEL              {P["n_mel"]}
#define N_MFCC             {P["n_mfcc"]}
#define FMIN               {float(P["fmin"])}f
#define FMAX               {float(P["fmax"])}f
#define N_BANDS            {P["n_bands"]}
#define N_FEATURES         {2 + P["n_mfcc"]}   /* RMS + centroid + MFCCs */
#define FRAME_MS           {frame_ms:.4f}f

/* ---- Pinos ---- */
#define PIN_I2S_BCK        {pins["i2s_bck"]}
#define PIN_I2S_WS         {pins["i2s_ws"]}
#define PIN_I2S_DATA       {pins["i2s_data"]}
#define PIN_LED            {pins["led"]}
#define PIN_BUZZER         {pins["buzzer"]}

/* ---- I2S ---- */
/* INMP441: L/R em {i2s["channel"].upper()} => lemos o slot {i2s["channel"]}. */
#define I2S_CHANNEL_LEFT   {1 if i2s["channel"] == "left" else 0}
#define DMA_BUF_COUNT      {i2s["dma_buf_count"]}
#define DMA_FRAME_NUM      {i2s["dma_frame_num"]}

/* ---- Serial ---- */
#define SERIAL_BAUD        {ser["baud"]}

/* ---- Detector ---- */
#define LIMIAR_FAKE        {float(det["limiar_fake"])}f
#define STATS_PERIOD_S     {det["stats_period_s"]}

#endif /* CONFIG_H */
"""

sdkconfig = f"""# GERADO POR tools/gen_config.py — NAO EDITE A MAO.
CONFIG_ESP_CONSOLE_UART_BAUDRATE={ser["baud"]}
CONFIG_FREERTOS_HZ=1000
CONFIG_ESP_MAIN_TASK_STACK_SIZE=4096
CONFIG_ESPTOOLPY_FLASHSIZE_4MB=y
"""

(ROOT / "firmware" / "include" / "config.h").write_text(config_h)
(ROOT / "firmware" / "sdkconfig.defaults").write_text(sdkconfig)
print("gerado: firmware/include/config.h")
print("gerado: firmware/sdkconfig.defaults")
