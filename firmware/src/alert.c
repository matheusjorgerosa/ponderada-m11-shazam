#include "alert.h"
#include "config.h"

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "driver/gpio.h"
#include "esp_log.h"
#include "esp_timer.h"
#if BUZZER_ENABLED
#include "driver/ledc.h"
#endif

static const char *TAG = "alert";

/* Cada LED tem seu proprio prazo. Nada de vTaskDelay: dormir aqui pararia a
 * task_detect de consumir a q_features e derrubaria frames — o desligamento e
 * por deadline, checado a cada volta do laco. */
static int64_t anomalia_ate = 0;
static int64_t musica_ate   = 0;

#if BUZZER_ENABLED
#define BUZZER_TIMER LEDC_TIMER_0
#define BUZZER_CANAL LEDC_CHANNEL_0
#define BUZZER_MODO  LEDC_LOW_SPEED_MODE

static void buzzer_init(void)
{
    ledc_timer_config_t t = {
        .speed_mode      = BUZZER_MODO,
        .timer_num       = BUZZER_TIMER,
        .duty_resolution = LEDC_TIMER_10_BIT,
        .freq_hz         = BUZZER_HZ,
        .clk_cfg         = LEDC_AUTO_CLK,
    };
    ledc_timer_config(&t);

    ledc_channel_config_t c = {
        .gpio_num   = PIN_BUZZER,
        .speed_mode = BUZZER_MODO,
        .channel    = BUZZER_CANAL,
        .timer_sel  = BUZZER_TIMER,
        .duty       = 0,
        .hpoint     = 0,
    };
    ledc_channel_config(&c);
}

static void buzzer_set(int ligado)
{
    ledc_set_duty(BUZZER_MODO, BUZZER_CANAL, ligado ? 512 : 0);   /* 50% */
    ledc_update_duty(BUZZER_MODO, BUZZER_CANAL);
}
#else
static void buzzer_init(void) {}
static void buzzer_set(int ligado) { (void)ligado; }
#endif

void alert_init(void)
{
    gpio_config_t cfg = {
        .pin_bit_mask = (1ULL << PIN_LED_ANOMALIA) | (1ULL << PIN_LED_MUSICA),
        .mode         = GPIO_MODE_OUTPUT,
        .pull_up_en   = GPIO_PULLUP_DISABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type    = GPIO_INTR_DISABLE,
    };
    gpio_config(&cfg);
    gpio_set_level(PIN_LED_ANOMALIA, 0);
    gpio_set_level(PIN_LED_MUSICA, 0);
    buzzer_init();

    /* Autoteste: pisca os dois no boot. Sem isso, "o LED nao acende" e
     * ambiguo entre pino errado, ligacao errada e nada tendo sido detectado.
     * Roda no app_main, antes das tasks, entao pode bloquear. */
    for (int i = 0; i < 3; i++) {
        gpio_set_level(PIN_LED_ANOMALIA, 1);
        gpio_set_level(PIN_LED_MUSICA, 1);
        vTaskDelay(pdMS_TO_TICKS(120));
        gpio_set_level(PIN_LED_ANOMALIA, 0);
        gpio_set_level(PIN_LED_MUSICA, 0);
        vTaskDelay(pdMS_TO_TICKS(120));
    }
    ESP_LOGI(TAG, "autoteste: anomalia GPIO%d · musica GPIO%d · 3 piscadas",
             PIN_LED_ANOMALIA, PIN_LED_MUSICA);
}

void alert_trigger(void)
{
    gpio_set_level(PIN_LED_ANOMALIA, 1);
    buzzer_set(1);
    anomalia_ate = esp_timer_get_time() + (int64_t)ALERT_MS * 1000;
}

void alert_musica(void)
{
    gpio_set_level(PIN_LED_MUSICA, 1);
    musica_ate = esp_timer_get_time() + (int64_t)MUSICA_MS * 1000;
}

void alert_update(void)
{
    int64_t agora = esp_timer_get_time();

    if (anomalia_ate != 0 && agora >= anomalia_ate) {
        gpio_set_level(PIN_LED_ANOMALIA, 0);
        buzzer_set(0);
        anomalia_ate = 0;
    }
    if (musica_ate != 0 && agora >= musica_ate) {
        gpio_set_level(PIN_LED_MUSICA, 0);
        musica_ate = 0;
    }
}
