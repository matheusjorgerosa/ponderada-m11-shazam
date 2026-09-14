#ifndef DETECTOR_H
#define DETECTOR_H

#include <stdbool.h>

/* Erro de reconstrucao do autoencoder sobre as features normalizadas.
 * Quanto maior, mais o frame destoa do que o modelo viu treinando. */
float detector_score(const float *features);

/* Threshold do model_weights.h, exposto pro stream do dashboard. */
float detector_threshold(void);

/* Aplica o threshold com debounce de DEBOUNCE_N frames consecutivos.
 * Tem estado interno — chame uma vez por frame, so da task_detect. */
bool detector_is_anomaly(float score);

#endif /* DETECTOR_H */
