#ifndef AUDIO_CAPTURE_H
#define AUDIO_CAPTURE_H

#include <stddef.h>
#include "esp_err.h"

/* Inicializa o I2S em modo master RX lendo o INMP441. */
esp_err_t audio_capture_init(void);

/* Le FRAME_SIZE amostras e devolve normalizadas em [-1.0, 1.0).
 * Bloqueia ate o frame inteiro chegar. `out` precisa ter FRAME_SIZE floats. */
esp_err_t audio_capture_read_frame(float *out);

#endif /* AUDIO_CAPTURE_H */
