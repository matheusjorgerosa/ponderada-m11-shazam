#include "audio_capture.h"
#include "config.h"

#include <string.h>

#include "freertos/FreeRTOS.h"
#include "driver/i2s_std.h"
#include "esp_log.h"

static const char *TAG = "audio";

static i2s_chan_handle_t rx_chan = NULL;

/* O INMP441 entrega 24 bits alinhados no topo de um slot de 32.
 * Deslocar 8 bits recupera o inteiro de 24 bits com sinal; dividir por 2^23
 * normaliza pra [-1, 1). */
#define SHIFT_TO_24BIT 8
#define SCALE_24BIT    8388608.0f

static int32_t raw[FRAME_SIZE];

esp_err_t audio_capture_init(void)
{
    i2s_chan_config_t chan_cfg = I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_0, I2S_ROLE_MASTER);
    chan_cfg.dma_desc_num  = DMA_BUF_COUNT;
    chan_cfg.dma_frame_num = DMA_FRAME_NUM;
    chan_cfg.auto_clear    = false;

    esp_err_t err = i2s_new_channel(&chan_cfg, NULL, &rx_chan);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "i2s_new_channel falhou: %s", esp_err_to_name(err));
        return err;
    }

    i2s_std_config_t std_cfg = {
        .clk_cfg  = I2S_STD_CLK_DEFAULT_CONFIG(SAMPLE_RATE),
        .slot_cfg = I2S_STD_PHILIPS_SLOT_DEFAULT_CONFIG(I2S_DATA_BIT_WIDTH_32BIT,
                                                        I2S_SLOT_MODE_MONO),
        .gpio_cfg = {
            .mclk = I2S_GPIO_UNUSED,
            .bclk = PIN_I2S_BCK,
            .ws   = PIN_I2S_WS,
            .dout = I2S_GPIO_UNUSED,
            .din  = PIN_I2S_DATA,
            .invert_flags = { .mclk_inv = false, .bclk_inv = false, .ws_inv = false },
        },
    };

    /* Tem que casar com o pino L/R do modulo: GND = esquerdo, VDD = direito.
     * Errar aqui e a causa de "so zero" ou "so ruido" em 90% dos casos. */
#if I2S_CHANNEL_LEFT
    std_cfg.slot_cfg.slot_mask = I2S_STD_SLOT_LEFT;
#else
    std_cfg.slot_cfg.slot_mask = I2S_STD_SLOT_RIGHT;
#endif

    err = i2s_channel_init_std_mode(rx_chan, &std_cfg);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "i2s_channel_init_std_mode falhou: %s", esp_err_to_name(err));
        return err;
    }

    err = i2s_channel_enable(rx_chan);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "i2s_channel_enable falhou: %s", esp_err_to_name(err));
        return err;
    }

    ESP_LOGI(TAG, "I2S ok: %d Hz, BCK=%d WS=%d DATA=%d, canal %s",
             SAMPLE_RATE, PIN_I2S_BCK, PIN_I2S_WS, PIN_I2S_DATA,
             I2S_CHANNEL_LEFT ? "esquerdo" : "direito");
    return ESP_OK;
}

esp_err_t audio_capture_read_frame(float *out)
{
    size_t lidos = 0;
    esp_err_t err = i2s_channel_read(rx_chan, raw, sizeof(raw), &lidos, portMAX_DELAY);
    if (err != ESP_OK) {
        return err;
    }
    if (lidos != sizeof(raw)) {
        ESP_LOGW(TAG, "frame curto: %u de %u bytes", (unsigned)lidos, (unsigned)sizeof(raw));
        return ESP_ERR_INVALID_SIZE;
    }

    for (int i = 0; i < FRAME_SIZE; i++) {
        out[i] = (float)(raw[i] >> SHIFT_TO_24BIT) / SCALE_24BIT;
    }
    return ESP_OK;
}
