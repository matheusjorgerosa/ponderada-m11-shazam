#include "song_match.h"
#include "config.h"

#include <stdio.h>
#include <string.h>

#include "esp_log.h"

static const char *TAG = "music";

/* Banco gerado por music_id/build_db.py em firmware/src/song_db.c, ordenado
 * por hash. Vive em .rodata (flash), mapeada em memoria — a busca binaria le
 * direto dali, sem gastar RAM. */
extern const uint64_t song_db[];
extern const uint32_t song_db_n;

static const uint64_t *banco;
static uint32_t        n_entradas;

/* Ring de picos recentes. Cada pico guarda quantos alvos ainda pode aceitar:
 * o leque limita o fan-out por ancora, igual ao fingerprint.py. */
#define RING (DT_MAX + 1)
static uint8_t  ring_banda[RING][N_SUPER];
static uint8_t  ring_cota[RING][N_SUPER];
static uint8_t  ring_n[RING];
static uint32_t frame_atual;

/* Histograma de votos. static, nao local: 9,4 KB na pilha de 4 KB da
 * task_detect seria estouro silencioso. */
static uint16_t hist[MAX_MUSICAS][N_OFFSETS];
static uint32_t frames_na_janela;

static inline uint32_t faz_hash(uint8_t f1, uint8_t f2, uint8_t dt)
{
    return ((uint32_t)f1 << 13) | ((uint32_t)f2 << 5) | (dt & 0x1F);
}

/* Primeira entrada com hash >= alvo. O hash mora nos 32 bits altos, entao
 * comparar o uint64 inteiro ja ordena por hash. */
static uint32_t limite_inferior(uint32_t alvo)
{
    uint64_t chave = (uint64_t)alvo << 32;
    uint32_t lo = 0, hi = n_entradas;
    while (lo < hi) {
        uint32_t meio = lo + (hi - lo) / 2;
        if (banco[meio] < chave) {
            lo = meio + 1;
        } else {
            hi = meio;
        }
    }
    return lo;
}

uint32_t song_match_init(void)
{
    banco = song_db;
    n_entradas = song_db_n;

    memset(hist, 0, sizeof(hist));
    memset(ring_n, 0, sizeof(ring_n));
    frame_atual = 0;
    frames_na_janela = 0;

    ESP_LOGI(TAG, "banco: %lu entradas (%lu KB) · votos_min %d · janela %d frames",
             (unsigned long)n_entradas,
             (unsigned long)(n_entradas * sizeof(uint64_t) / 1024),
             VOTOS_MIN, JANELA_FRAMES);
    if (n_entradas < 2) {
        ESP_LOGE(TAG, "banco vazio — rode music_id/build_db.py e recompile");
    }
    return n_entradas;
}

int song_match_frame(const uint8_t *picos, int n_picos, int *votos)
{
    int melhor_musica = -1;
    uint16_t melhor_votos = 0;

    /* 1. Pareia cada pico novo com as ancoras do passado.
     *
     * A ordem de emissao difere do fingerprint.py (la o laco e por ancora,
     * aqui por alvo), mas o CONJUNTO de pares e o mesmo: cada ancora aceita
     * ate LEQUE alvos, e os alvos chegam na mesma ordem nos dois lados. */
    for (int i = 0; i < n_picos; i++) {
        uint8_t f2 = picos[i];

        for (int dt = DT_MAX; dt >= DT_MIN; dt--) {
            if ((uint32_t)dt > frame_atual) {
                continue;                       /* ainda nao ha passado */
            }
            uint32_t t1 = frame_atual - dt;
            uint32_t slot = t1 % RING;

            for (int k = 0; k < ring_n[slot]; k++) {
                if (ring_cota[slot][k] == 0) {
                    continue;
                }
                ring_cota[slot][k]--;

                uint32_t h = faz_hash(ring_banda[slot][k], f2, (uint8_t)dt);
                uint32_t idx = limite_inferior(h);

                while (idx < n_entradas && (uint32_t)(banco[idx] >> 32) == h) {
                    uint32_t carga = (uint32_t)(banco[idx] & 0xFFFFFFFFu);
                    uint32_t sid   = carga >> 24;
                    uint32_t t_db  = carga & 0xFFFFFFu;

                    if (sid < MAX_MUSICAS) {
                        /* Offset circular: constante enquanto a musica toca,
                         * e sem fronteira de janela. */
                        /* N_OFFSETS e potencia de 2, entao o modulo vira
                         * mascara — importa porque isto roda por par. */
                        uint32_t off = (t_db - t1) & (N_OFFSETS - 1);
                        uint16_t v = ++hist[sid][off];
                        if (v > melhor_votos) {
                            melhor_votos = v;
                            melhor_musica = (int)sid;
                        }
                    }
                    idx++;
                }
            }
        }
    }

    /* 2. Insere os picos deste frame, com a cota cheia. */
    uint32_t slot = frame_atual % RING;
    ring_n[slot] = (uint8_t)(n_picos > N_SUPER ? N_SUPER : n_picos);
    for (int i = 0; i < ring_n[slot]; i++) {
        ring_banda[slot][i] = picos[i];
        ring_cota[slot][i]  = LEQUE;
    }
    frame_atual++;

    /* 3. Decide.
     *
     * Cruzar VOTOS_MIN nao basta. No inicio da consulta ha poucos votos e uma
     * musica errada pode liderar por acaso — exigir so o limiar absoluto
     * errava 2 de 10 no teste contra o Python, que ve a consulta inteira
     * antes de decidir.
     *
     * Entao o vencedor tambem precisa bater o segundo colocado entre as
     * OUTRAS musicas por MARGEM_VOTOS_X10/10. Se ainda nao bate, o histograma
     * NAO zera: os votos continuam somando e a decisao espera o quadro ficar
     * claro. Bins vizinhos da mesma musica nao contam como concorrencia. */
    if (votos) {
        *votos = melhor_votos;
    }
    if (melhor_votos >= VOTOS_MIN) {
        uint16_t segundo = 0;
        for (int m = 0; m < MAX_MUSICAS; m++) {
            if (m == melhor_musica) {
                continue;
            }
            for (int o = 0; o < N_OFFSETS; o++) {
                if (hist[m][o] > segundo) {
                    segundo = hist[m][o];
                }
            }
        }
        if ((uint32_t)melhor_votos * 10 >=
            (uint32_t)MARGEM_VOTOS_X10 * (segundo ? segundo : 1)) {
            memset(hist, 0, sizeof(hist));
            frames_na_janela = 0;
            return melhor_musica;
        }
    }

    if (++frames_na_janela >= JANELA_FRAMES) {
        memset(hist, 0, sizeof(hist));
        frames_na_janela = 0;
    }
    return -1;
}
