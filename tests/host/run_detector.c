/* Harness de host: le linhas CSV de 15 features do stdin, imprime o score do
 * detector.c (as 4 matmuls em C) — um por linha. Compara-se com o .onnx. */

#include <stdio.h>
#include <stdlib.h>

#include "config.h"
#include "../../firmware/src/detector.h"
#include "../../firmware/src/rtos.h"

/* detector.c traz a task_detect junto, que referencia o alerta, o stream e os
 * objetos do RTOS. Nada disso e chamado aqui — so detector_score — mas o
 * linker precisa dos simbolos. */
float             audio_pool[AUDIO_POOL_SIZE][FRAME_SIZE];
SemaphoreHandle_t sem_free_buffers, mtx_stats;
QueueHandle_t     q_audio, q_features;
stats_t           stats;
void stats_add(uint32_t a, uint32_t b, uint32_t c) { (void)a; (void)b; (void)c; }
stats_t stats_snapshot(void) { return stats; }
void alert_init(void) {}
void alert_trigger(void) {}
void alert_update(void) {}
void stream_emit(const feature_frame_t *ff, float s) { (void)ff; (void)s; }

int main(void)
{
    float f[N_FEATURES];
    char linha[1024];

    while (fgets(linha, sizeof(linha), stdin)) {
        char *p = linha;
        int ok = 1;
        for (int i = 0; i < N_FEATURES; i++) {
            char *fim;
            f[i] = strtof(p, &fim);
            if (fim == p) { ok = 0; break; }
            p = (*fim == ',') ? fim + 1 : fim;
        }
        if (ok) {
            printf("%.9g\n", detector_score(f));
        }
    }
    return 0;
}
