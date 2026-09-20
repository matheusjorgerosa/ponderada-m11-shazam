#include "features.h"
#include "config.h"
#include "rtos.h"

#include <inttypes.h>
#include <math.h>
#include <stdio.h>
#include <string.h>

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_dsp.h"
#include "esp_log.h"
#include "esp_timer.h"

static const char *TAG = "features";

/* O pipeline abaixo tem que bater bit a bit com tools/dashboard/dsp.py.
 * Onde houver escolha de convencao, a nota diz qual foi feita — o Python
 * copia daqui, nao o contrario. */

static float hann[FRAME_SIZE];
static float fft_buf[2 * FRAME_SIZE];        /* re,im intercalados */
static float mag[N_FFT_BINS];
static float mel_edges[N_MEL + 2];           /* posicoes de bin das bordas */
static float mel_energy[N_MEL];
static int   band_edges[N_BANDS + 1];        /* bordas em indice de bin */
static int   fp_edges[N_BANDS_FP + 1];       /* idem, resolucao do fingerprint */
static float band_escala;                    /* ganho coerente da janela */

static float hz_to_mel(float hz) { return 2595.0f * log10f(1.0f + hz / 700.0f); }
static float mel_to_hz(float m)  { return 700.0f * (powf(10.0f, m / 2595.0f) - 1.0f); }

esp_err_t features_init(void)
{
    esp_err_t err = dsps_fft2r_init_fc32(NULL, CONFIG_DSP_MAX_FFT_SIZE);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "dsps_fft2r_init_fc32 falhou: %s", esp_err_to_name(err));
        return err;
    }

    /* Hann periodica (divide por N, nao por N-1) — e a que o librosa usa por
     * padrao na STFT. A simetrica daria um espectro levemente diferente. */
    for (int i = 0; i < FRAME_SIZE; i++) {
        hann[i] = 0.5f * (1.0f - cosf(2.0f * (float)M_PI * (float)i / (float)FRAME_SIZE));
    }

    /* N_MEL+2 bordas igualmente espacadas na escala mel entre FMIN e FMAX;
     * cada filtro e o triangulo que vai da borda k ate a k+2, com pico em k+1. */
    float mel_min = hz_to_mel(FMIN);
    float mel_max = hz_to_mel(FMAX);
    for (int i = 0; i < N_MEL + 2; i++) {
        float m  = mel_min + (mel_max - mel_min) * (float)i / (float)(N_MEL + 1);
        float hz = mel_to_hz(m);
        mel_edges[i] = hz * (float)FRAME_SIZE / (float)SAMPLE_RATE;
    }

    /* Ganho coerente da Hann: uma senoide de amplitude A vira um pico de
     * A/2 * sum(hann) na FFT. Dividir por isso faz o dB virar dBFS — sem
     * essa normalizacao qualquer som alto satura em 255 e o colormap do
     * espectrograma vira chapado. */
    float soma = 0.0f;
    for (int i = 0; i < FRAME_SIZE; i++) {
        soma += hann[i];
    }
    band_escala = 2.0f / soma;

    /* Bordas das bandas: log-espacadas entre FMIN e FMAX, nos mesmos limites
     * da mel, pra que o dsp.py reuse os parametros. Duas tabelas — 64 bandas
     * para o dashboard, N_BANDS_FP para o fingerprint. */
    float lg_min = log10f(FMIN);
    float lg_max = log10f(FMAX);
    for (int b = 0; b <= N_BANDS; b++) {
        float hz  = powf(10.0f, lg_min + (lg_max - lg_min) * (float)b / (float)N_BANDS);
        int   bin = (int)(hz * (float)FRAME_SIZE / (float)SAMPLE_RATE);
        band_edges[b] = (bin > N_FFT_BINS - 1) ? (N_FFT_BINS - 1) : bin;
    }
    for (int b = 0; b <= N_BANDS_FP; b++) {
        float hz  = powf(10.0f, lg_min + (lg_max - lg_min) * (float)b / (float)N_BANDS_FP);
        int   bin = (int)(hz * (float)FRAME_SIZE / (float)SAMPLE_RATE);
        fp_edges[b] = (bin > N_FFT_BINS - 1) ? (N_FFT_BINS - 1) : bin;
    }

    ESP_LOGI(TAG, "FFT %d pontos, %d filtros mel (%.0f–%.0f Hz), %d MFCCs",
             FRAME_SIZE, N_MEL, FMIN, FMAX, N_MFCC);
    return ESP_OK;
}

float features_rms(const float *x, int n)
{
    float acc = 0.0f;
    for (int i = 0; i < n; i++) {
        acc += x[i] * x[i];
    }
    return sqrtf(acc / (float)n);
}

const float *features_spectrum(void) { return mag; }

/* MAXIMO da banda, nao media: nas bandas graves o espaco log e mais estreito
 * que um bin, e a media achataria tom puro contra o piso vizinho. O que se
 * quer ver no espectrograma e justamente a raia fina. */
static void comprime(const int *bordas, int n_bandas, uint8_t *out)
{
    for (int b = 0; b < n_bandas; b++) {
        int k0 = bordas[b];
        int k1 = bordas[b + 1];
        if (k1 <= k0) {
            k1 = k0 + 1;
        }
        if (k1 > N_FFT_BINS) {
            k1 = N_FFT_BINS;
        }

        float pico = 0.0f;
        for (int k = k0; k < k1; k++) {
            if (mag[k] > pico) {
                pico = mag[k];
            }
        }

        float db = 20.0f * log10f(pico * band_escala + 1e-9f);
        float u  = (db - DB_MIN) / (DB_MAX - DB_MIN) * 255.0f;
        out[b] = (u < 0.0f) ? 0 : (u > 255.0f ? 255 : (uint8_t)u);
    }
}

void features_bands(uint8_t *out)    { comprime(band_edges, N_BANDS, out); }
void features_fp_bands(uint8_t *out) { comprime(fp_edges, N_BANDS_FP, out); }

/* Limiar SEM estado: media das bandas do proprio frame mais uma margem.
 *
 * A tentacao aqui e usar media movel, mas ela tem memoria infinita — no
 * fingerprint.py comecaria no inicio da musica e no device viria rodando desde
 * o boot com som ambiente. Os dois nunca produziriam os mesmos picos, e a
 * divergencia seria sistematica, nao ruido.
 *
 * Tudo inteiro: soma em uint32, divisao inteira, comparacao inteira. O Python
 * reproduz isso exatamente, sem tolerancia de ponto flutuante. */
int features_peaks(const uint8_t *fp_bands, uint8_t *picos)
{
    uint32_t soma = 0;
    for (int b = 0; b < N_BANDS_FP; b++) {
        soma += fp_bands[b];
    }
    int limiar = (int)(soma / N_BANDS_FP) + MARGEM_U8;

    int n = 0;
    for (int g = 0; g < N_SUPER; g++) {
        int b0 = g * N_BANDS_FP / N_SUPER;
        int b1 = (g + 1) * N_BANDS_FP / N_SUPER;

        int melhor = b0;
        for (int b = b0 + 1; b < b1; b++) {
            if (fp_bands[b] > fp_bands[melhor]) {
                melhor = b;      /* empate fica com o indice menor */
            }
        }
        if (fp_bands[melhor] > limiar) {
            picos[n++] = (uint8_t)melhor;
        }
    }
    return n;
}

/* Centroide espectral: media das frequencias ponderada pela magnitude.
 * Em silencio o denominador vai a zero, entao devolvemos 0 em vez de NaN —
 * NaN envenenaria a normalizacao do autoencoder no Batch 6. */
static float spectral_centroid(void)
{
    float num = 0.0f, den = 0.0f;
    const float hz_por_bin = (float)SAMPLE_RATE / (float)FRAME_SIZE;

    for (int k = 0; k < N_FFT_BINS; k++) {
        num += (float)k * hz_por_bin * mag[k];
        den += mag[k];
    }
    return (den > 1e-12f) ? (num / den) : 0.0f;
}

/* Energia de cada filtro mel sobre o espectro de POTENCIA (mag^2), depois
 * log natural. O dsp.py precisa usar potencia e log natural tambem. */
static void mel_filterbank(void)
{
    for (int m = 0; m < N_MEL; m++) {
        float esq = mel_edges[m];
        float pico = mel_edges[m + 1];
        float dir = mel_edges[m + 2];
        float acc = 0.0f;

        int k0 = (int)ceilf(esq);
        int k1 = (int)floorf(dir);
        if (k0 < 0) k0 = 0;
        if (k1 > N_FFT_BINS - 1) k1 = N_FFT_BINS - 1;

        for (int k = k0; k <= k1; k++) {
            float w;
            if ((float)k <= pico) {
                w = (pico > esq) ? ((float)k - esq) / (pico - esq) : 0.0f;
            } else {
                w = (dir > pico) ? (dir - (float)k) / (dir - pico) : 0.0f;
            }
            if (w > 0.0f) {
                acc += w * mag[k] * mag[k];
            }
        }
        mel_energy[m] = logf(acc + 1e-10f);
    }
}

/* DCT-II ortonormal — mesma convencao de scipy.fftpack.dct(type=2,
 * norm='ortho'), que e a que o librosa usa pra MFCC. */
static void dct2(float *out)
{
    const float esc0 = sqrtf(1.0f / (float)N_MEL);
    const float esck = sqrtf(2.0f / (float)N_MEL);

    for (int k = 0; k < N_MFCC; k++) {
        float acc = 0.0f;
        for (int n = 0; n < N_MEL; n++) {
            acc += mel_energy[n] *
                   cosf((float)M_PI * (float)k * ((float)n + 0.5f) / (float)N_MEL);
        }
        out[k] = acc * ((k == 0) ? esc0 : esck);
    }
}

void features_compute(const float *x, float *out)
{
    out[0] = features_rms(x, FRAME_SIZE);

    /* FFT complexa com a parte imaginaria zerada. O truque de empacotar dois
     * sinais reais numa FFT de N/2 economizaria ~1 ms, e o frame tem 64 ms
     * de orcamento — nao vale o codigo ilegivel que gera. */
    for (int i = 0; i < FRAME_SIZE; i++) {
        fft_buf[2 * i]     = x[i] * hann[i];
        fft_buf[2 * i + 1] = 0.0f;
    }
    dsps_fft2r_fc32(fft_buf, FRAME_SIZE);
    dsps_bit_rev_fc32(fft_buf, FRAME_SIZE);

    for (int k = 0; k < N_FFT_BINS; k++) {
        float re = fft_buf[2 * k];
        float im = fft_buf[2 * k + 1];
        mag[k] = sqrtf(re * re + im * im);
    }

    out[1] = spectral_centroid();

    mel_filterbank();
    dct2(&out[2]);
}

/* ------------------------------------------------------------------ *
 * Task 2 — extracao de features.
 *
 * Bloquear na q_audio aqui e legitimo: essa task e consumidora, e ficar
 * parada esperando frame nao atrasa ninguem. Quem nao pode bloquear e a
 * captura.
 * ------------------------------------------------------------------ */
void task_features(void *arg)
{
    (void)arg;
    audio_msg_t     m;
    feature_frame_t ff;

    while (1) {
        if (xQueueReceive(q_audio, &m, portMAX_DELAY) != pdTRUE) {
            continue;
        }

#if FORCE_DELAY_FEATURES_MS > 0
        vTaskDelay(pdMS_TO_TICKS(FORCE_DELAY_FEATURES_MS));
#endif

        ff.seq       = m.seq;
        ff.t_capture = m.t_capture;
        ff.t_detect  = 0;
        features_compute(audio_pool[m.idx], ff.f);
        features_bands(ff.bands);
        ff.t_features = esp_timer_get_time();

        /* Devolve o buffer ANTES de enfileirar. Quanto antes ele volta pro
         * pool, menor a janela em que a captura pode ficar sem vaga. */
        xSemaphoreGive(sem_free_buffers);

        if (xQueueSend(q_features, &ff, 0) != pdTRUE) {
            stats_drop(0);   /* sem printf: vale o mesmo motivo da captura */
        }
    }
}
