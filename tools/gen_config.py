#!/usr/bin/env python3
"""Gera firmware/include/config.h e firmware/sdkconfig.defaults a partir do params.json.

Rode sempre que mexer no params.json:
    python3 tools/gen_config.py
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
P = json.loads((ROOT / "params.json").read_text())

pins, i2s, ser, det, rtos = P["pins"], P["i2s"], P["serial"], P["detector"], P["rtos"]
modes, stream, mid = P["modes"], P["stream"], P["music_id"]
n_fft_bins = P["frame_size"] // 2 + 1
fps = P["sample_rate"] / P["frame_size"]
janela_frames = int(P["music_id"]["janela_s"] * fps)
trecho_frames = int(P["music_id"]["trecho_s"] * fps)
# Offset CIRCULAR. Com offset linear seria preciso zerar o relogio da query a
# cada janela, e todo par cuja ancora caisse antes da fronteira se perderia —
# ate 25% deles. (t_banco - t_query) mod N e constante para um casamento
# verdadeiro e uniforme para colisao, sem fronteira nenhuma.
n_offsets = P["music_id"]["offsets"]
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
#define SETTLE_MS          {i2s["settle_ms"]}

/* ---- Serial ---- */
#define SERIAL_BAUD        {ser["baud"]}

/* ---- Identificacao de musica ---- */
#define N_BANDS_FP         {mid["n_bands_fp"]}
#define N_SUPER            {mid["n_super"]}
#define MARGEM_U8          {mid["margem_u8"]}
#define LEQUE              {mid["leque"]}
#define DT_MIN             {mid["dt_min"]}
#define DT_MAX             {mid["dt_max"]}
#define MAX_MUSICAS        {mid["max_musicas"]}
#define VOTOS_MIN          {mid["votos_min"]}
#define COOLDOWN_FRAMES    {int(mid["cooldown_s"] * fps)}
#define MARGEM_VOTOS_X10   {mid["margem_votos_x10"]}
#define JANELA_FRAMES      {janela_frames}
#define N_OFFSETS          {n_offsets}   /* potencia de 2: o modulo vira mascara */

/* ---- RTOS ---- */
#define AUDIO_POOL_SIZE    {rtos["pool_size"]}
#define Q_AUDIO_DEPTH      {rtos["q_audio_depth"]}
#define Q_FEATURES_DEPTH   {rtos["q_features_depth"]}
#define PRIO_CAPTURE       {rtos["prio_capture"]}
#define CORE_CAPTURE       {rtos["core_capture"]}
#define PRIO_FEATURES      {rtos["prio_features"]}
#define CORE_FEATURES      {rtos["core_features"]}
#define PRIO_DETECT        {rtos["prio_detect"]}
#define CORE_DETECT        {rtos["core_detect"]}

/* ---- Modos ---- */
#define MODE_DATASET       {modes["dataset"]}
#define MODE_STREAM        {modes["stream"]}
#define MODE_MUSIC_ID      {modes["music_id"]}

/* ---- Stream do dashboard ---- */
#define DB_MIN             {float(stream["db_min"])}f
#define DB_MAX             {float(stream["db_max"])}f

/* ---- Detector ---- */
#define DEBOUNCE_N         {det["debounce_n"]}
#define STATS_PERIOD_S     {det["stats_period_s"]}
#define ALERT_MS           {det["alert_ms"]}
#define BUZZER_ENABLED     {det["buzzer_enabled"]}
#define BUZZER_HZ          {det["buzzer_hz"]}

/* Atrasos artificiais do teste de estresse. 0 = desligado. */
#define FORCE_DELAY_FEATURES_MS  {det["force_delay_features_ms"]}
#define FORCE_DELAY_DETECT_MS    {det["force_delay_detect_ms"]}

#endif /* CONFIG_H */
"""

sdkconfig = f"""# GERADO POR tools/gen_config.py — NAO EDITE A MAO.

# O Kconfig do ESP-IDF declara o baud do console como
#   prompt "UART console baud rate" if ESP_CONSOLE_UART_CUSTOM
# ou seja: sem CUSTOM o simbolo nao tem prompt, nao e configuravel, e um valor
# aqui e ignorado EM SILENCIO — fica em 115200 e o serial sai ilegivel.
CONFIG_ESP_CONSOLE_UART_CUSTOM=y
CONFIG_ESP_CONSOLE_UART_NUM=0
CONFIG_ESP_CONSOLE_UART_TX_GPIO=1
CONFIG_ESP_CONSOLE_UART_RX_GPIO=3
CONFIG_ESP_CONSOLE_UART_BAUDRATE={ser["baud"]}
CONFIG_FREERTOS_HZ=1000
CONFIG_ESP_MAIN_TASK_STACK_SIZE=4096
CONFIG_ESPTOOLPY_FLASHSIZE_4MB=y
"""

(ROOT / "firmware" / "include" / "config.h").write_text(config_h)
(ROOT / "firmware" / "sdkconfig.defaults").write_text(sdkconfig)

# O ESP-IDF so le o sdkconfig.defaults quando gera o sdkconfig do zero. Se o
# antigo sobreviver, mudanca nenhuma daqui pega — e o sintoma e serial ilegivel
# por baud errado, que nao aponta pra ca.
obsoleto = ROOT / "firmware" / "sdkconfig.esp32dev"
if obsoleto.exists():
    obsoleto.unlink()
    print("removido: firmware/sdkconfig.esp32dev (obsoleto)")

# O song_match.c referencia o banco sempre. Sem a Fase 2 gerada, um stub
# vazio mantem a Fase 1 compilando — build_db.py sobrescreve quando rodar.
db_c = ROOT / "firmware" / "src" / "song_db.c"
if not db_c.exists():
    db_c.write_text("/* STUB — rode music_id/build_db.py para gerar o banco. */\n"
                    "#include <stdint.h>\n\n"
                    "const uint32_t song_db_n = 0;\n"
                    "const uint64_t song_db[1] = {0};\n")
    print("gerado: firmware/src/song_db.c (stub vazio)")

print("gerado: firmware/include/config.h")
print("gerado: firmware/sdkconfig.defaults")
