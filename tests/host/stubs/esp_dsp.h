/* Stub de host: DFT ingenua O(N^2) no lugar da FFT do esp-dsp.
 *
 * O par (dsps_fft2r_fc32, dsps_bit_rev_fc32) do esp-dsp deixa o resultado em
 * ordem natural. Aqui a DFT ja produz ordem natural, entao bit_rev vira no-op
 * e o features.c compila sem mudar nada.
 *
 * Isso valida o codigo NOSSO — magnitude, centroide, filterbank mel e DCT.
 * NAO valida a chamada ao esp-dsp em si; so hardware faz isso. */
#ifndef ESP_DSP_H
#define ESP_DSP_H

#include <math.h>
#include <stdlib.h>
#include "esp_err.h"

#define CONFIG_DSP_MAX_FFT_SIZE 4096

static inline esp_err_t dsps_fft2r_init_fc32(void *tab, int size) {
    (void)tab; (void)size; return ESP_OK;
}

static inline esp_err_t dsps_fft2r_fc32(float *data, int n) {
    float *out = (float *)malloc(sizeof(float) * 2 * n);
    if (!out) return ESP_FAIL;
    for (int k = 0; k < n; k++) {
        double re = 0.0, im = 0.0;
        for (int t = 0; t < n; t++) {
            double ang = -2.0 * M_PI * (double)k * (double)t / (double)n;
            re += data[2 * t] * cos(ang) - data[2 * t + 1] * sin(ang);
            im += data[2 * t] * sin(ang) + data[2 * t + 1] * cos(ang);
        }
        out[2 * k] = (float)re;
        out[2 * k + 1] = (float)im;
    }
    for (int i = 0; i < 2 * n; i++) data[i] = out[i];
    free(out);
    return ESP_OK;
}

static inline esp_err_t dsps_bit_rev_fc32(float *data, int n) {
    (void)data; (void)n; return ESP_OK;   /* a DFT acima ja sai ordenada */
}
#endif
