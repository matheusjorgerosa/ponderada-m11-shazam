#ifndef DETECTOR_H
#define DETECTOR_H

#include <stdbool.h>

/* Batch 2: threshold burro de RMS. O autoencoder entra no Batch 6. */
bool detector_is_anomaly(const float *features);

#endif /* DETECTOR_H */
