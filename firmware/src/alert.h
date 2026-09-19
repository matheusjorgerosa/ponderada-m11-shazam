#ifndef ALERT_H
#define ALERT_H

void alert_init(void);

/* Acende o LED por ALERT_MS. Nao bloqueia. */
void alert_trigger(void);

/* Pisca n vezes para identificar qual musica casou. Nao bloqueia — o
 * alert_update() toca a sequencia. */
void alert_pattern(int n);

/* Avanca o LED (desligamento por deadline, ou proxima piscada do padrao).
 * Chame periodicamente. */
void alert_update(void);

#endif /* ALERT_H */
