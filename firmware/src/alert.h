#ifndef ALERT_H
#define ALERT_H

void alert_init(void);

/* Acende o LED por ALERT_MS. Nao bloqueia. */
void alert_trigger(void);

/* Apaga o LED quando o tempo expira. Chame periodicamente. */
void alert_update(void);

#endif /* ALERT_H */
