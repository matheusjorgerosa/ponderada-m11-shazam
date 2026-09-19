#include "alert.h"
#include "config.h"

#include "driver/gpio.h"
#include "esp_timer.h"
#if BUZZER_ENABLED
#include "driver/ledc.h"
#endif

/* Sem vTaskDelay aqui: dormir na task de deteccao pra segurar o LED aceso
 * pararia de consumir a q_features e derrubaria frames. O desligamento e
 * por deadline, checado a cada volta do loop. */
static int64_t desliga_em = 0;

/* Padrao de piscadas: n piscadas de PISCA_MS, para dizer QUAL musica casou.
 * Sem vTaskDelay, pelo mesmo motivo do alerta simples — a task_detect precisa
 * continuar consumindo a q_features. */
#define PISCA_MS 150
static int     piscadas_restantes = 0;
static bool    pisca_aceso = false;
static int64_t proxima_troca = 0;

#if BUZZER_ENABLED
#define BUZZER_TIMER   LEDC_TIMER_0
#define BUZZER_CANAL   LEDC_CHANNEL_0
#define BUZZER_MODO    LEDC_LOW_SPEED_MODE

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
    ledc_set_duty(BUZZER_MODO, BUZZER_CANAL, ligado ? 512 : 0);  /* 50% */
    ledc_update_duty(BUZZER_MODO, BUZZER_CANAL);
}
#else
static void buzzer_init(void) {}
static void buzzer_set(int ligado) { (void)ligado; }
#endif

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
    buzzer_init();
}

void alert_pattern(int n)
{
    piscadas_restantes = n * 2;      /* cada piscada = acende + apaga */
    pisca_aceso = false;
    proxima_troca = esp_timer_get_time();
    desliga_em = 0;                  /* o padrao tem prioridade sobre o alerta */
}

void alert_trigger(void)
{
    gpio_set_level(PIN_LED, 1);
    buzzer_set(1);
    desliga_em = esp_timer_get_time() + (int64_t)ALERT_MS * 1000;
}

void alert_update(void)
{
    int64_t agora = esp_timer_get_time();

    if (piscadas_restantes > 0) {
        if (agora >= proxima_troca) {
            pisca_aceso = !pisca_aceso;
            gpio_set_level(PIN_LED, pisca_aceso);
            proxima_troca = agora + (int64_t)PISCA_MS * 1000;
            piscadas_restantes--;
            if (piscadas_restantes == 0) {
                gpio_set_level(PIN_LED, 0);
            }
        }
        return;                      /* enquanto pisca, ignora o alerta simples */
    }

    if (desliga_em != 0 && esp_timer_get_time() >= desliga_em) {
        gpio_set_level(PIN_LED, 0);
        buzzer_set(0);
        desliga_em = 0;
    }
}
