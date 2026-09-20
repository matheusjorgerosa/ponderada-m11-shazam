/* Harness de host: le FRAME_SIZE floats em texto do stdin, imprime as 15
 * features em CSV no stdout. Compila o features.c do firmware sem alterar
 * uma linha dele — os stubs de tests/host/stubs/ cobrem o que e do ESP32. */

#include <stdio.h>
#include <stdlib.h>

/* Por caminho relativo, nao por -I: firmware/src/ tem um features.h, e poe-lo
 * no include path faz ele sequestrar o <features.h> da glibc, que o stdio.h
 * inclui. O erro resultante nao diz nada sobre colisao de nome. */
#include "../../firmware/src/features.h"
#include "../../firmware/src/rtos.h"

/* task_features referencia esses simbolos; main.c os define no firmware. */
float             audio_pool[AUDIO_POOL_SIZE][FRAME_SIZE];
SemaphoreHandle_t sem_free_buffers = NULL;
QueueHandle_t     q_audio          = NULL;
QueueHandle_t     q_features       = NULL;
SemaphoreHandle_t mtx_stats        = NULL;
stats_t           stats            = {0};

void stats_add(uint32_t a, uint32_t b) { (void)a; (void)b; }
void stats_drop(int a) { (void)a; }
stats_t stats_snapshot(void) { return stats; }

static float x[FRAME_SIZE];

int main(void)
{
    if (features_init() != ESP_OK) {
        fprintf(stderr, "features_init falhou\n");
        return 1;
    }

    for (int i = 0; i < FRAME_SIZE; i++) {
        if (scanf("%f", &x[i]) != 1) {
            fprintf(stderr, "esperava %d amostras, recebi %d\n", FRAME_SIZE, i);
            return 1;
        }
    }

    float f[N_FEATURES];
    features_compute(x, f);

    for (int i = 0; i < N_FEATURES; i++) {
        printf("%.9g%s", f[i], (i == N_FEATURES - 1) ? "\n" : ",");
    }
    return 0;
}
