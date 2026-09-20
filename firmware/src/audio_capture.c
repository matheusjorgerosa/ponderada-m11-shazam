#include "audio_capture.h"
#include "config.h"
#include "rtos.h"

#include <inttypes.h>
#include <stdio.h>
#include <string.h>

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "driver/i2s_std.h"
#include "esp_log.h"
#include "esp_timer.h"

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

    /* So da pra saber se o mic esta ligado DEPOIS que o clock roda: sem BCK o
     * INMP441 deixa o SD em alta impedancia, igualzinho a um fio solto. Com o
     * clock rodando a diferenca e obvia — mic vivo produz dado que varia, pino
     * solto devolve sempre o mesmo valor (0 ou 0xFFFFFFFF, conforme o pull). */
    size_t lidos = 0;
    for (int t = 0; t < 3; t++) {
        i2s_channel_read(rx_chan, raw, sizeof(raw), &lidos, portMAX_DELAY);
    }
    int constante = 1;
    for (int i = 1; i < FRAME_SIZE; i++) {
        if (raw[i] != raw[0]) { constante = 0; break; }
    }
    if (constante) {
        ESP_LOGE(TAG, "todas as amostras iguais (%ld): o mic nao esta dirigindo "
                      "o SD. Confira VDD=3V3, GND e o fio em GPIO%d.",
                 (long)raw[0], PIN_I2S_DATA);
    } else {
        ESP_LOGI(TAG, "mic presente, dados variando");
    }

    /* Descarta o transiente de assentamento do mic. */
    int descartar = (SETTLE_MS * SAMPLE_RATE) / (1000 * FRAME_SIZE);
    for (int i = 0; i < descartar; i++) {
        i2s_channel_read(rx_chan, raw, sizeof(raw), &lidos, portMAX_DELAY);
    }
    ESP_LOGI(TAG, "assentamento: %d frames descartados (%d ms)", descartar, SETTLE_MS);

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

/* ------------------------------------------------------------------ *
 * Task 1 — captura. Prioridade mais alta do sistema.
 *
 * Regra inviolavel: nunca bloqueia por contencao. Todo take/send usa
 * timeout 0. A unica espera permitida e a do I2S, que nao e contencao —
 * e o relogio do sistema, um frame a cada FRAME_MS.
 * ------------------------------------------------------------------ */
void task_capture(void *arg)
{
    (void)arg;

    /* Quando nao ha buffer livre ainda somos obrigados a drenar o I2S: parar
     * de ler faria o DMA transbordar e corromper o alinhamento do stream.
     * Entao lemos pro lixo e contabilizamos o descarte. */
    static float descarte[FRAME_SIZE];

    /* Alocacao round-robin. Funciona porque ha exatamente um produtor e um
     * consumidor, e a q_audio e FIFO: os buffers sao devolvidos na mesma
     * ordem ciclica em que foram tomados. O semaforo garante que o proximo
     * indice ja esta livre. */
    uint8_t  next = 0;
    uint32_t seq  = 0;

    while (1) {
        bool tem_buffer = (xSemaphoreTake(sem_free_buffers, 0) == pdTRUE);
        float *destino  = tem_buffer ? audio_pool[next] : descarte;

        if (audio_capture_read_frame(destino) != ESP_OK) {
            if (tem_buffer) {
                xSemaphoreGive(sem_free_buffers);
            }
            continue;
        }

        if (!tem_buffer) {
            /* Sem printf aqui, de proposito. Esta task nao pode bloquear, e
             * printf bloqueia quando o FIFO de TX do UART enche — que e
             * exatamente o que acontece quando ha muitos descartes. O contador
             * basta; o STATS reporta a cada STATS_PERIOD_S. */
            stats_drop(1);
            seq++;
            continue;
        }

        audio_msg_t m = {
            .idx       = next,
            .seq       = seq++,
            .t_capture = esp_timer_get_time(),
        };

        /* O semaforo ja garantiu vaga; se falhar, algo quebrou a invariante. */
        if (xQueueSend(q_audio, &m, 0) != pdTRUE) {
            xSemaphoreGive(sem_free_buffers);
            stats_drop(1);
            continue;
        }

        next = (next + 1) % AUDIO_POOL_SIZE;
        stats_add(1, 0);
    }
}
