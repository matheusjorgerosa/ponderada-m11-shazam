#ifndef ALERT_H
#define ALERT_H

/* Dois LEDs, um por tipo de evento — o terminal diz os detalhes. */
void alert_init(void);

/* Anomalia: acende o LED de anomalia por ALERT_MS. */
void alert_trigger(void);

/* Musica identificada: acende o LED de musica por MUSICA_MS. */
void alert_musica(void);

/* Apaga cada LED quando o prazo dele vence. Nao bloqueia — chame a cada
 * volta do laco da task_detect. */
void alert_update(void);

#endif /* ALERT_H */
