#include "features.h"
#include "config.h"
#include "rtos.h"

#include <inttypes.h>
#include <math.h>
#include <stdio.h>
#include <string.h>

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_timer.h"

float features_rms(const float *x, int n)
{
    float acc = 0.0f;
    for (int i = 0; i < n; i++) {
        acc += x[i] * x[i];
    }
    return sqrtf(acc / (float)n);
}

/* ------------------------------------------------------------------ *
 * Task 2 — extracao de features.
 *
 * Bloquear na q_audio aqui e legitimo: essa task e consumidora, e ficar
 * parada esperando frame nao atrasa ninguem. Quem nao pode bloquear e a
 * captura.
 * ------------------------------------------------------------------ */
void task_features(void *arg)
{
    (void)arg;
    audio_msg_t     m;
    feature_frame_t ff;

    while (1) {
        if (xQueueReceive(q_audio, &m, portMAX_DELAY) != pdTRUE) {
            continue;
        }

#if FORCE_DELAY_FEATURES_MS > 0
        vTaskDelay(pdMS_TO_TICKS(FORCE_DELAY_FEATURES_MS));
#endif

        memset(&ff, 0, sizeof(ff));   /* Batch 3 preenche f[1..14]; por ora zeros */
        ff.seq       = m.seq;
        ff.t_capture = m.t_capture;
        ff.f[0]      = features_rms(audio_pool[m.idx], FRAME_SIZE);
        ff.t_features = esp_timer_get_time();

        /* Devolve o buffer ANTES de enfileirar. Quanto antes ele volta pro
         * pool, menor a janela em que a captura pode ficar sem vaga. */
        xSemaphoreGive(sem_free_buffers);

        if (xQueueSend(q_features, &ff, 0) != pdTRUE) {
            stats_add(0, 1, 0);
            printf("DROP features seq=%" PRIu32 " (q_features cheia)\n", ff.seq);
        }
    }
}
