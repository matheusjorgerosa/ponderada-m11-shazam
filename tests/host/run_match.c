/* Harness de host: le picos do stdin (um frame por linha, indices separados
 * por virgula, linha vazia = nenhum pico) e imprime o resultado do casamento
 * de cada frame no formato  <musica>,<votos>  com musica = -1 quando nao casa.
 *
 * Existe para o validate_match.py comparar a votacao do song_match.c com a do
 * build_db.py. */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "config.h"
#include "../../firmware/src/song_match.h"

int main(void)
{
    char linha[256];
    uint8_t picos[N_SUPER];

    song_match_init();

    while (fgets(linha, sizeof(linha), stdin)) {
        int n = 0;
        for (char *tok = strtok(linha, ",\n"); tok && n < N_SUPER;
             tok = strtok(NULL, ",\n")) {
            if (*tok >= '0' && *tok <= '9') {
                picos[n++] = (uint8_t)atoi(tok);
            }
        }
        int votos = 0;
        int m = song_match_frame(picos, n, &votos);
        printf("%d,%d\n", m, votos);
    }
    return 0;
}
