/* Batch 2 — arquitetura RTOS completa, com deteccao ainda fake.
 *
 *   task_capture  (prio 6, core 1)  I2S -> pool de buffers
 *        | q_audio (indice do buffer, prof. 4)   + sem_free_buffers (0..4)
 *   task_features (prio 4, core 1)  pool -> feature_frame_t
 *        | q_features (por valor, prof. 8)
 *   task_detect   (prio 3, core 0)  threshold de RMS -> LED
 *
 * As prioridades seguem o prazo de cada etapa: so a captura tem prazo
 * fisico (o DMA do I2S nao espera). As outras duas, se atrasarem, apenas
 * aumentam a latencia — nao perdem dado.
 */

#include <stdio.h>

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_log.h"

#include "alert.h"
#include "audio_capture.h"
#include "config.h"
#include "rtos.h"

static const char *TAG = "main";

/* Definicoes dos objetos declarados em rtos.h. */
float             audio_pool[AUDIO_POOL_SIZE][FRAME_SIZE];
SemaphoreHandle_t sem_free_buffers = NULL;
QueueHandle_t     q_audio          = NULL;
QueueHandle_t     q_features       = NULL;
SemaphoreHandle_t mtx_stats        = NULL;
stats_t           stats            = {0};

/* Mutex e nao semaforo binario aqui de proposito: as tres tasks tem
 * prioridades diferentes, e o mutex do FreeRTOS faz heranca de prioridade.
 * Sem isso, a task de deteccao (prio 3) segurando o lock poderia ser
 * preemptada por qualquer coisa enquanto a captura (prio 6) espera —
 * inversao de prioridade classica. */
void stats_add(uint32_t d_captured, uint32_t d_dropped, uint32_t d_anomalies)
{
    if (xSemaphoreTake(mtx_stats, portMAX_DELAY) == pdTRUE) {
        stats.frames_captured    += d_captured;
        stats.frames_dropped     += d_dropped;
        stats.anomalies_detected += d_anomalies;
        xSemaphoreGive(mtx_stats);
    }
}

stats_t stats_snapshot(void)
{
    stats_t copia = {0};
    if (xSemaphoreTake(mtx_stats, portMAX_DELAY) == pdTRUE) {
        copia = stats;
        xSemaphoreGive(mtx_stats);
    }
    return copia;
}

void app_main(void)
{
    ESP_LOGI(TAG, "detector de anomalias acusticas — batch 2");
    ESP_LOGI(TAG, "frame=%d amostras (%.1f ms) @ %d Hz", FRAME_SIZE, FRAME_MS, SAMPLE_RATE);

    sem_free_buffers = xSemaphoreCreateCounting(AUDIO_POOL_SIZE, AUDIO_POOL_SIZE);
    q_audio          = xQueueCreate(Q_AUDIO_DEPTH, sizeof(audio_msg_t));
    q_features       = xQueueCreate(Q_FEATURES_DEPTH, sizeof(feature_frame_t));
    mtx_stats        = xSemaphoreCreateMutex();

    if (!sem_free_buffers || !q_audio || !q_features || !mtx_stats) {
        ESP_LOGE(TAG, "falha ao criar objetos do RTOS, abortando");
        return;
    }

    alert_init();

    if (audio_capture_init() != ESP_OK) {
        ESP_LOGE(TAG, "falha ao inicializar o I2S, abortando");
        return;
    }

    ESP_LOGI(TAG, "pool=%d q_audio=%d q_features=%d (feature_frame_t=%u bytes)",
             AUDIO_POOL_SIZE, Q_AUDIO_DEPTH, Q_FEATURES_DEPTH,
             (unsigned)sizeof(feature_frame_t));
#if FORCE_DELAY_FEATURES_MS > 0 || FORCE_DELAY_DETECT_MS > 0
    ESP_LOGW(TAG, "teste de estresse ligado: features +%d ms, detect +%d ms",
             FORCE_DELAY_FEATURES_MS, FORCE_DELAY_DETECT_MS);
#endif

    xTaskCreatePinnedToCore(task_capture,  "capture",  4096, NULL, PRIO_CAPTURE,  NULL, CORE_CAPTURE);
    xTaskCreatePinnedToCore(task_features, "features", 4096, NULL, PRIO_FEATURES, NULL, CORE_FEATURES);
    xTaskCreatePinnedToCore(task_detect,   "detect",   4096, NULL, PRIO_DETECT,   NULL, CORE_DETECT);
}
