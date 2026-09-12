#ifndef FEATURES_H
#define FEATURES_H

/* RMS do sinal no tempo. No Batch 2 e a unica feature real;
 * centroid e MFCCs entram no Batch 3. */
float features_rms(const float *x, int n);

#endif /* FEATURES_H */
