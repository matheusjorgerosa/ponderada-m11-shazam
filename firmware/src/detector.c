#include "detector.h"
#include "alert.h"
#include "config.h"
#include "rtos.h"

#include <inttypes.h>
#include <stdio.h>

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_timer.h"

bool detector_is_anomaly(const float *features)
{
    return features[0] > LIMIAR_FAKE;   /* features[0] == RMS */
}

/* Latencia ponta a ponta acumulada. So esta task toca nessas variaveis,
 * entao nao precisam de mutex — ao contrario de stats, que tres tasks
 * escrevem. */
static int64_t  lat_soma = 0;
static int64_t  lat_max  = 0;
static uint32_t lat_n    = 0;

static void imprime_stats(void)
{
    stats_t s = stats_snapshot();

    int64_t lat_media = (lat_n > 0) ? (lat_soma / lat_n) : 0;

    printf("STATS captured=%" PRIu32 " dropped=%" PRIu32 " anomalies=%" PRIu32
           " q_audio=%u/%u q_features=%u/%u"
           " lat_media_us=%" PRId64 " lat_max_us=%" PRId64
           " uptime_s=%" PRId64 "\n",
           s.frames_captured, s.frames_dropped, s.anomalies_detected,
           (unsigned)uxQueueMessagesWaiting(q_audio), Q_AUDIO_DEPTH,
           (unsigned)uxQueueMessagesWaiting(q_features), Q_FEATURES_DEPTH,
           lat_media, lat_max,
           esp_timer_get_time() / 1000000);

    lat_soma = 0;
    lat_max  = 0;
    lat_n    = 0;
}

/* ------------------------------------------------------------------ *
 * Task 3 — deteccao. Menor prioridade, no core 0.
 *
 * O receive tem timeout de 1 s em vez de portMAX_DELAY pra que as
 * estatisticas continuem saindo mesmo se o pipeline travar — sem isso um
 * silencio no log seria ambiguo entre "parou" e "esta indo bem".
 * ------------------------------------------------------------------ */
void task_detect(void *arg)
{
    (void)arg;
    feature_frame_t ff;
    int64_t ultimo_stats = esp_timer_get_time();

    while (1) {
        if (xQueueReceive(q_features, &ff, pdMS_TO_TICKS(1000)) == pdTRUE) {
#if FORCE_DELAY_DETECT_MS > 0
            vTaskDelay(pdMS_TO_TICKS(FORCE_DELAY_DETECT_MS));
#endif
            bool anomalia = detector_is_anomaly(ff.f);
            ff.t_detect   = esp_timer_get_time();

            int64_t lat = ff.t_detect - ff.t_capture;
            lat_soma += lat;
            lat_n++;
            if (lat > lat_max) {
                lat_max = lat;
            }

            if (anomalia) {
                alert_trigger();
                stats_add(0, 0, 1);
                printf("ANOMALIA seq=%" PRIu32 " rms=%.6f limiar=%.6f lat_us=%" PRId64 "\n",
                       ff.seq, ff.f[0], LIMIAR_FAKE, lat);
            }
        }

        alert_update();

        int64_t agora = esp_timer_get_time();
        if (agora - ultimo_stats >= (int64_t)STATS_PERIOD_S * 1000000) {
            imprime_stats();
            ultimo_stats = agora;
        }
    }
}
