#include "alert.h"
#include "config.h"

#include "driver/gpio.h"
#include "esp_timer.h"

/* Sem vTaskDelay aqui: dormir na task de deteccao pra segurar o LED aceso
 * pararia de consumir a q_features e derrubaria frames. O desligamento e
 * por deadline, checado a cada volta do loop. */
static int64_t desliga_em = 0;

void alert_init(void)
{
    gpio_config_t cfg = {
        .pin_bit_mask = (1ULL << PIN_LED),
        .mode         = GPIO_MODE_OUTPUT,
        .pull_up_en   = GPIO_PULLUP_DISABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type    = GPIO_INTR_DISABLE,
    };
    gpio_config(&cfg);
    gpio_set_level(PIN_LED, 0);
}

void alert_trigger(void)
{
    gpio_set_level(PIN_LED, 1);
    desliga_em = esp_timer_get_time() + (int64_t)ALERT_MS * 1000;
}

void alert_update(void)
{
    if (desliga_em != 0 && esp_timer_get_time() >= desliga_em) {
        gpio_set_level(PIN_LED, 0);
        desliga_em = 0;
    }
}
