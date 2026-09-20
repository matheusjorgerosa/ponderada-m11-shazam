#ifndef FEATURES_H
#define FEATURES_H

#include <stdint.h>

#include "esp_err.h"

/* Monta a janela de Hann, a filterbank mel e as tabelas da FFT. */
esp_err_t features_init(void);

/* RMS do sinal no tempo. */
float features_rms(const float *x, int n);

/* Preenche out[N_FEATURES]: [0]=RMS [1]=centroid [2..14]=MFCC.
 * Deixa o magnitude spectrum do frame disponivel em features_spectrum(). */
void features_compute(const float *x, float *out);

/* Magnitude spectrum do ultimo frame processado, N_FFT_BINS valores.
 * So a task_features escreve aqui. */
const float *features_spectrum(void);

/* Comprime o magnitude spectrum em N_BANDS bandas log, cada uma em dB
 * escalado pra 0..255. Roda dentro da task_features, dona do espectro —
 * fazer isso no stream.c seria corrida com a proxima FFT. */
void features_bands(uint8_t *out);

/* Idem, mas em N_BANDS_FP bandas — a resolucao fina que o hashing precisa.
 * As 64 do dashboard dariam so 6 bits por frequencia, e o espaco de hash
 * ficaria mais denso que o proprio banco. */
void features_fp_bands(uint8_t *out);

/* Pico mais forte de cada uma das N_SUPER super-bandas, descartando o que nao
 * passa da media do frame mais MARGEM_U8. Escreve ate N_SUPER indices de banda
 * em `picos` e devolve quantos sobraram.
 *
 * Tudo em aritmetica inteira de proposito: assim o dsp.py produz exatamente os
 * mesmos picos, bit a bit, e o teste de validacao e igualdade exata. */
int features_peaks(const uint8_t *fp_bands, uint8_t *picos);

#endif /* FEATURES_H */
