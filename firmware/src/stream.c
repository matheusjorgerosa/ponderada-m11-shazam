#include "stream.h"
#include "config.h"

#include <inttypes.h>
#include <stdio.h>

/* Monta a linha inteira num buffer e manda de uma vez. Um printf por campo
 * seriam 69 chamadas por frame, ~1080 por segundo — o overhead apareceria
 * na latencia. */
static char linha[512];

void stream_emit(const feature_frame_t *ff, float score)
{
#if MODE_STREAM
    int n = snprintf(linha, sizeof(linha), "S,%" PRId64 ",%.6f,%.1f,%.6f",
                     ff->t_capture, ff->f[0], ff->f[1], score);

    for (int i = 0; i < N_MFCC && n > 0 && n < (int)sizeof(linha) - 16; i++) {
        n += snprintf(linha + n, sizeof(linha) - n, ",%.3f", ff->f[2 + i]);
    }

    for (int b = 0; b < N_BANDS && n > 0 && n < (int)sizeof(linha) - 6; b++) {
        n += snprintf(linha + n, sizeof(linha) - n, ",%u", (unsigned)ff->bands[b]);
    }

    if (n > 0 && n < (int)sizeof(linha)) {
        puts(linha);
    }
#else
    (void)ff;
    (void)score;
#endif
}
