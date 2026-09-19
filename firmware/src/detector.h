#ifndef DETECTOR_H
#define DETECTOR_H

#include <stdbool.h>

/* Erro de reconstrucao do autoencoder sobre as features normalizadas.
 * Quanto maior, mais o frame destoa do que o modelo viu treinando. */
float detector_score(const float *features);

/* Threshold do model_weights.h, exposto pro stream do dashboard. */
float detector_threshold(void);

/* Aplica o threshold com debounce de DEBOUNCE_N frames consecutivos.
 *
 * Devolve true enquanto o sinal ESTIVER anomalo — todo frame acima do
 * threshold depois do debounce — para o LED poder ficar aceso o tempo todo.
 * Em `novo_episodio` marca só a transicao, que e o que conta como um alerta
 * nas estatisticas e no log. Confundir os dois fazia o LED piscar uma vez e
 * apagar com o som ainda acontecendo.
 *
 * Tem estado interno — chame uma vez por frame, so da task_detect. */
bool detector_is_anomaly(float score, bool *novo_episodio);

#endif /* DETECTOR_H */
