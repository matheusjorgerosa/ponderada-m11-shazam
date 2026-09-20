/* Objetos de concorrencia compartilhados pelas tres tasks.
 * Definidos em main.c, que e quem os cria. */
#ifndef RTOS_H
#define RTOS_H

#include <stdint.h>

#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/semphr.h"

#include "config.h"

/* Mensagem da q_audio: carrega o INDICE do buffer no pool, nunca as 1024
 * amostras. Copiar 4 KB por frame pela fila anularia o sentido do pool.
 * O seq e o timestamp viajam junto porque sao da captura, e so ela sabe. */
typedef struct {
    uint8_t  idx;
    uint32_t seq;
    int64_t  t_capture;   /* us, medido no fim da leitura I2S */
} audio_msg_t;

/* Mensagem da q_features: viaja POR VALOR (~80 bytes). Aqui copiar sai mais
 * barato que manter um segundo pool com mais um semaforo pra gerenciar.
 * Os tres timestamps sao o que o Batch 7 usa pra fatiar a latencia. */
typedef struct {
    uint32_t seq;
    float    f[N_FEATURES];   /* [0]=RMS  [1]=centroid  [2..14]=MFCC */
    uint8_t  bands[N_BANDS];  /* espectro em 64 bandas log, dB escalado 0..255 */
    int64_t  t_capture;
    int64_t  t_features;
    int64_t  t_detect;
} feature_frame_t;

typedef struct {
    uint32_t frames_captured;
    uint32_t frames_dropped;        /* total, = capture + features */
    uint32_t dropped_capture;       /* pool sem buffer livre */
    uint32_t dropped_features;      /* q_features cheia */
    uint32_t anomalies_detected;
} stats_t;

/* Pool de buffers de audio: task_capture escreve, task_features le.
 * sem_free_buffers conta quantos estao livres (init AUDIO_POOL_SIZE). */
extern float             audio_pool[AUDIO_POOL_SIZE][FRAME_SIZE];
extern SemaphoreHandle_t sem_free_buffers;

extern QueueHandle_t q_audio;
extern QueueHandle_t q_features;

/* stats so pode ser tocado com mtx_stats na mao — use os helpers abaixo. */
extern SemaphoreHandle_t mtx_stats;
extern stats_t           stats;

void    stats_add(uint32_t d_captured, uint32_t d_anomalies);
/* Registra um descarte na etapa indicada; soma tambem no total. */
void    stats_drop(int na_captura);
stats_t stats_snapshot(void);

/* Entrypoints das tasks, cada um no seu modulo. */
void task_capture(void *arg);    /* audio_capture.c */
void task_features(void *arg);   /* features.c      */
void task_detect(void *arg);     /* detector.c      */

#endif /* RTOS_H */
