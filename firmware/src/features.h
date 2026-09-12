#ifndef FEATURES_H
#define FEATURES_H

#include "esp_err.h"

/* Monta a janela de Hann, a filterbank mel e as tabelas da FFT. */
esp_err_t features_init(void);

/* RMS do sinal no tempo. */
float features_rms(const float *x, int n);

/* Preenche out[N_FEATURES]: [0]=RMS [1]=centroid [2..14]=MFCC.
 * Deixa o magnitude spectrum do frame disponivel em features_spectrum(). */
void features_compute(const float *x, float *out);

/* Magnitude spectrum do ultimo frame processado, N_FFT_BINS valores.
 * So a task_features escreve aqui; o Batch 4 le pra montar as bandas log. */
const float *features_spectrum(void);

#endif /* FEATURES_H */
