#ifndef STREAM_H
#define STREAM_H

#include "rtos.h"

/* Emite um frame compacto pro dashboard, uma linha de texto por frame:
 *   S,<t_us>,<rms>,<centroid>,<score>,<threshold>,<mfcc0..12>,<b0..b63>
 * Nao manda o espectro cru de 513 bins nem audio bruto — nao cabe no serial.
 *
 * Os MFCCs vao junto (o PLANO nao os listava) pra que o botao de gravar do
 * dashboard produza CSV com as 15 features que o modelo consome. Custa ~120
 * bytes por frame; a ~15,6 fps sao 6,5 KB/s num canal de 92 KB/s. */
/* O threshold vai em toda linha (ele e constante) pra que a linha desenhada no
 * dashboard seja sempre a que o device esta usando de fato — uma copia no
 * params.json dessincronizaria no dia em que voce reflashar outro modelo. */
void stream_emit(const feature_frame_t *ff, float score);

#endif /* STREAM_H */
