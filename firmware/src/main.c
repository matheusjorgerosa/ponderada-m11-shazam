/* Batch 1 — prova de vida do microfone.
 * Uma unica task: le frames do I2S, calcula RMS e imprime no serial.
 * A arquitetura RTOS de verdade (3 tasks, filas, semaforo) entra no Batch 2. */

#include <math.h>
#include <stdio.h>

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_log.h"
#include "esp_timer.h"

#include "config.h"
#include "audio_capture.h"

static const char *TAG = "main";

static float frame[FRAME_SIZE];

static float rms(const float *x, int n)
{
    float acc = 0.0f;
    for (int i = 0; i < n; i++) {
        acc += x[i] * x[i];
    }
    return sqrtf(acc / (float)n);
}

static void task_capture(void *arg)
{
    (void)arg;
    uint32_t n = 0;

    while (1) {
        int64_t t0 = esp_timer_get_time();
        if (audio_capture_read_frame(frame) != ESP_OK) {
            continue;
        }
        int64_t t1 = esp_timer_get_time();

        float r  = rms(frame, FRAME_SIZE);
        float db = 20.0f * log10f(r + 1e-9f);

        printf("frame=%lu rms=%.6f dbfs=%.1f leitura_us=%lld\n",
               (unsigned long)n++, r, db, t1 - t0);
    }
}

void app_main(void)
{
    ESP_LOGI(TAG, "detector de anomalias acusticas — batch 1");
    ESP_LOGI(TAG, "frame=%d amostras (%.1f ms) @ %d Hz", FRAME_SIZE, FRAME_MS, SAMPLE_RATE);

    if (audio_capture_init() != ESP_OK) {
        ESP_LOGE(TAG, "falha ao inicializar o I2S, abortando");
        return;
    }

    xTaskCreatePinnedToCore(task_capture, "capture", 4096, NULL, 6, NULL, 1);
}
