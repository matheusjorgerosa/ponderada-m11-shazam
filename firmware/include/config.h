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

/* ---- Serial ---- */
#define SERIAL_BAUD        921600

/* ---- Detector ---- */
#define LIMIAR_FAKE        0.05f
#define STATS_PERIOD_S     5

#endif /* CONFIG_H */
