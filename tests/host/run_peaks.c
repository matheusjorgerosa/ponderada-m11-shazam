/* Harness de host: le floats do stdin, processa em frames de FRAME_SIZE e
 * imprime os picos de cada frame, um frame por linha (indices separados por
 * virgula, linha vazia se nenhum pico passou do limiar).
 *
 * Existe para o validate_peaks.py comparar contra o dsp.peaks(). Como o peak
 * picking e todo inteiro, a comparacao e igualdade exata. */

#include <stdio.h>
#include <stdlib.h>

#include "../../firmware/src/features.h"
#include "../../firmware/src/rtos.h"

/* features.c arrasta a task_features junto; o linker precisa dos simbolos. */
float             audio_pool[AUDIO_POOL_SIZE][FRAME_SIZE];
SemaphoreHandle_t sem_free_buffers, mtx_stats;
QueueHandle_t     q_audio, q_features;
stats_t           stats;
void stats_add(uint32_t a, uint32_t b) { (void)a; (void)b; }
void stats_drop(int a) { (void)a; }

static float   x[FRAME_SIZE];
static float   f[N_FEATURES];
static uint8_t fp[N_BANDS_FP];
static uint8_t picos[N_SUPER];

int main(void)
{
    if (features_init() != ESP_OK) {
        fprintf(stderr, "features_init falhou\n");
        return 1;
    }

    while (1) {
        int lidos = 0;
        while (lidos < FRAME_SIZE && scanf("%f", &x[lidos]) == 1) {
            lidos++;
        }
        if (lidos < FRAME_SIZE) {
            break;                 /* frame incompleto no fim: descarta */
        }

        features_compute(x, f);    /* preenche o magnitude spectrum */
        features_fp_bands(fp);
        int n = features_peaks(fp, picos);

        for (int i = 0; i < n; i++) {
            printf("%u%s", (unsigned)picos[i], (i == n - 1) ? "" : ",");
        }
        printf("\n");
    }
    return 0;
}
