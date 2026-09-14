/* Stub de host: so o suficiente pra features.c compilar. A task_features
 * nunca e chamada pelo harness — so features_init/features_compute. */
#ifndef FREERTOS_H
#define FREERTOS_H
#include <stdint.h>
typedef void *QueueHandle_t;
typedef void *SemaphoreHandle_t;
typedef int   BaseType_t;
#define pdTRUE  1
#define pdFALSE 0
#define portMAX_DELAY 0xFFFFFFFF
#define pdMS_TO_TICKS(x) (x)
static inline BaseType_t xQueueReceive(QueueHandle_t q, void *b, uint32_t t) { (void)q;(void)b;(void)t; return pdFALSE; }
static inline BaseType_t xQueueSend(QueueHandle_t q, const void *b, uint32_t t) { (void)q;(void)b;(void)t; return pdFALSE; }
static inline BaseType_t xSemaphoreGive(SemaphoreHandle_t s) { (void)s; return pdTRUE; }
static inline unsigned uxQueueMessagesWaiting(QueueHandle_t q) { (void)q; return 0; }
static inline BaseType_t xSemaphoreTake(SemaphoreHandle_t s, uint32_t t) { (void)s;(void)t; return pdTRUE; }
#endif
