/* GERADO POR tools/gen_config.py A PARTIR DE params.json — NAO EDITE A MAO. */
#ifndef CONFIG_H
#define CONFIG_H

/* ---- DSP ---- */
#define SAMPLE_RATE        16000
#define FRAME_SIZE         1024
#define HOP_SIZE           1024
#define N_FFT_BINS         513
#define N_MEL              20
#define N_MFCC             13
#define FMIN               80.0f
#define FMAX               7800.0f
#define N_BANDS            64
#define N_FEATURES         15   /* RMS + centroid + MFCCs */
#define FRAME_MS           64.0000f

/* ---- Pinos ---- */
#define PIN_I2S_BCK        26
#define PIN_I2S_WS         25
#define PIN_I2S_DATA       33
#define PIN_LED            2
#define PIN_BUZZER         4

/* ---- I2S ---- */
/* INMP441: L/R em LEFT => lemos o slot left. */
#define I2S_CHANNEL_LEFT   1
#define DMA_BUF_COUNT      4
#define DMA_FRAME_NUM      512
#define SETTLE_MS          5000

/* ---- Serial ---- */
#define SERIAL_BAUD        921600

/* ---- Identificacao de musica ---- */
#define N_BANDS_FP         256
#define N_SUPER            6
#define MARGEM_U8          15
#define LEQUE              3
#define DT_MIN             1
#define DT_MAX             31
#define MAX_MUSICAS        10
#define VOTOS_MIN          60
#define RMS_MIN_MUSICA     0.025f
#define MARGEM_VOTOS_X10   15
#define JANELA_FRAMES      93
#define TRECHO_FRAMES      468
#define N_OFFSETS          468   /* = TRECHO_FRAMES, offset circular */

/* ---- RTOS ---- */
#define AUDIO_POOL_SIZE    4
#define Q_AUDIO_DEPTH      4
#define Q_FEATURES_DEPTH   8
#define PRIO_CAPTURE       6
#define CORE_CAPTURE       1
#define PRIO_FEATURES      4
#define CORE_FEATURES      1
#define PRIO_DETECT        3
#define CORE_DETECT        0

/* ---- Modos ---- */
#define MODE_DATASET       0
#define MODE_STREAM        1
#define MODE_MUSIC_ID      1

/* ---- Stream do dashboard ---- */
#define DB_MIN             -100.0f
#define DB_MAX             0.0f

/* ---- Detector ---- */
#define DEBOUNCE_N         3
#define STATS_PERIOD_S     5
#define ALERT_MS           500
#define BUZZER_ENABLED     0
#define BUZZER_HZ          2000

/* Atrasos artificiais do teste de estresse. 0 = desligado. */
#define FORCE_DELAY_FEATURES_MS  0
#define FORCE_DELAY_DETECT_MS    0

#endif /* CONFIG_H */
