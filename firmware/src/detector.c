#include "detector.h"
#include "alert.h"
#include "config.h"
#include "model_weights.h"
#include "rtos.h"
#include "song_match.h"
#include "stream.h"

#include <inttypes.h>
#include <stdio.h>

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_timer.h"

/* Uma camada densa: out[o] = sum_i w[o*n_in + i] * x[i] + b[o].
 * Quatro chamadas destas sao o modelo inteiro — sem TFLite, sem runtime
 * externo, sem quantizacao. Os pesos vem do model_weights.h, gerado pelo
 * train.py, e vivem em .rodata (flash), nao em RAM. */
static void densa(const float *x, int n_in,
                  const float *w, const float *b,
                  float *out, int n_out, int relu)
{
    for (int o = 0; o < n_out; o++) {
        const float *linha = w + o * n_in;
        float acc = b[o];
        for (int i = 0; i < n_in; i++) {
            acc += linha[i] * x[i];
        }
        out[o] = (relu && acc < 0.0f) ? 0.0f : acc;
    }
}

float detector_threshold(void) { return model_threshold; }

float detector_score(const float *features)
{
    float z[MODEL_N_IN];
    float h1[MODEL_H1], h2[MODEL_LATENT], h3[MODEL_H1];
    float recon[MODEL_N_IN];

    for (int i = 0; i < MODEL_N_IN; i++) {
        z[i] = (features[i] - model_mean[i]) / model_std[i];
    }

    densa(z,  MODEL_N_IN,   w_enc1, b_enc1, h1,    MODEL_H1,     1);
    densa(h1, MODEL_H1,     w_enc2, b_enc2, h2,    MODEL_LATENT, 1);
    densa(h2, MODEL_LATENT, w_dec1, b_dec1, h3,    MODEL_H1,     1);
    densa(h3, MODEL_H1,     w_dec2, b_dec2, recon, MODEL_N_IN,   0);  /* linear */

    float acc = 0.0f;
    for (int i = 0; i < MODEL_N_IN; i++) {
        float d = recon[i] - z[i];
        acc += d * d;
    }
    return acc / (float)MODEL_N_IN;
}

/* Debounce: um frame isolado acima do threshold quase sempre e ruido. Exigir
 * DEBOUNCE_N consecutivos custa DEBOUNCE_N*64 ms de latencia e corta quase
 * todo falso positivo. */
bool detector_is_anomaly(float score)
{
    static int seguidos = 0;

    if (score <= model_threshold) {
        seguidos = 0;
        return false;
    }

    seguidos++;
    if (seguidos == DEBOUNCE_N) {
        return true;        /* dispara uma vez; so rearma apos voltar ao normal */
    }
    return false;
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

    printf("STATS captured=%" PRIu32 " dropped=%" PRIu32
           " drop_cap=%" PRIu32 " drop_feat=%" PRIu32 " anomalies=%" PRIu32
           " q_audio=%u/%u q_features=%u/%u"
           " lat_media_us=%" PRId64 " lat_max_us=%" PRId64
           " uptime_s=%" PRId64 "\n",
           s.frames_captured, s.frames_dropped,
           s.dropped_capture, s.dropped_features, s.anomalies_detected,
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

#if MODE_MUSIC_ID
    song_match_init();
#endif
#if MODE_DATASET
    /* Cabecalho uma vez so; daqui pra frente o serial e CSV puro, sem log
     * nenhum, pra que o collect.py do Batch 5 possa ler linha a linha. */
    printf("rms,centroid");
    for (int i = 0; i < N_MFCC; i++) {
        printf(",mfcc%d", i);
    }
    printf("\n");
#endif

    while (1) {
        if (xQueueReceive(q_features, &ff, pdMS_TO_TICKS(1000)) == pdTRUE) {
#if FORCE_DELAY_DETECT_MS > 0
            vTaskDelay(pdMS_TO_TICKS(FORCE_DELAY_DETECT_MS));
#endif
#if MODE_MUSIC_ID
            /* Mesmo pipeline, algoritmo diferente: em vez do erro de
             * reconstrucao, casamento de fingerprint por votacao. As tasks,
             * filas, semaforo e mutex sao exatamente os mesmos. */
            int votos = 0;
            int musica = song_match_frame(ff.picos, ff.n_picos, &votos);
            float score   = (float)votos;
            bool anomalia = (musica >= 0);
            ff.t_detect   = esp_timer_get_time();
            if (anomalia) {
                alert_musica();
                printf("MATCH musica=%d votos=%d\n", musica + 1, votos);
            }
#else
            float score   = detector_score(ff.f);
            bool anomalia = detector_is_anomaly(score);
            ff.t_detect   = esp_timer_get_time();
#endif

#if MODE_DATASET
            printf("%.6f,%.2f", ff.f[0], ff.f[1]);
            for (int i = 0; i < N_MFCC; i++) {
                printf(",%.4f", ff.f[2 + i]);
            }
            printf("\n");
#endif
            stream_emit(&ff, score);

            /* Tres etapas separadas: cada uma inclui a espera na fila que a
             * precede, que e justamente onde o gargalo aparece. */
            int64_t lat_cf = ff.t_features - ff.t_capture;
            int64_t lat_fd = ff.t_detect   - ff.t_features;
            int64_t lat    = ff.t_detect   - ff.t_capture;
            lat_soma += lat;
            lat_n++;
            if (lat > lat_max) {
                lat_max = lat;
            }

            if (anomalia) {
#if !MODE_MUSIC_ID
                alert_trigger();
#endif
                stats_add(0, 1);
            }
#if !MODE_DATASET
#if MODE_MUSIC_ID
            printf("D,%" PRIu32 ",%.6f,%.6f,%d,%" PRId64 ",%" PRId64 ",%" PRId64 "\n",
                   ff.seq, score, (float)VOTOS_MIN, anomalia ? 1 : 0,
                   lat_cf, lat_fd, lat);
#else
            printf("D,%" PRIu32 ",%.6f,%.6f,%d,%" PRId64 ",%" PRId64 ",%" PRId64 "\n",
                   ff.seq, score, model_threshold, anomalia ? 1 : 0,
                   lat_cf, lat_fd, lat);
#endif
#endif
        }

        alert_update();

        int64_t agora = esp_timer_get_time();
        if (agora - ultimo_stats >= (int64_t)STATS_PERIOD_S * 1000000) {
#if !MODE_DATASET
            imprime_stats();
#endif
            ultimo_stats = agora;
        }
    }
}
