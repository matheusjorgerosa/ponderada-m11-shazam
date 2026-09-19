#ifndef SONG_MATCH_H
#define SONG_MATCH_H

#include <stdint.h>

/* Valida o banco embutido e zera o estado. Devolve quantas entradas tem. */
uint32_t song_match_init(void);

/* Consome os picos de um frame e acumula votos.
 *
 * Devolve o songID quando um casamento cruza VOTOS_MIN, ou -1. Dispara uma
 * vez por janela: depois de casar, o histograma zera.
 * Se `votos` nao for NULL, recebe a contagem do bin vencedor. */
int song_match_frame(const uint8_t *picos, int n_picos, int *votos);

#endif /* SONG_MATCH_H */
