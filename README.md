# Detector de Anomalias Acústicas

Sistema embarcado em ESP32 que captura áudio por um microfone I2S, extrai features
espectrais em tempo real e sinaliza desvios do perfil acústico normal do ambiente
usando um autoencoder treinado apenas com som normal.

Planejamento completo e cronograma: [`PLANO.md`](PLANO.md).

## Hardware

- ESP32 DevKit v1 (`esp32dev`)
- Microfone INMP441 (MEMS, I2S)
- LED indicador
- Buzzer (opcional)

## Ligação INMP441 ↔ ESP32

```
        INMP441                         ESP32 DevKit
     ┌───────────┐                    ┌──────────────┐
     │       VDD ├────────────────────┤ 3V3          │
     │       GND ├────────────────────┤ GND          │
     │       L/R ├──────┐             │              │
     │           │      └─────────────┤ GND          │  ← canal ESQUERDO
     │       WS  ├────────────────────┤ GPIO25       │
     │       SCK ├────────────────────┤ GPIO26       │
     │       SD  ├────────────────────┤ GPIO33       │
     └───────────┘                    │              │
                                      │              │
     LED ──[220Ω]──────────────────── ┤ GPIO2        │
      └──────────────────────────────┤ GND          │
                                      │              │
     Buzzer ────────────────────────── ┤ GPIO4        │
      └──────────────────────────────┤ GND          │
                                      └──────────────┘
```

| INMP441 | ESP32   | Observação                                          |
|---------|---------|-----------------------------------------------------|
| VDD     | 3V3     | **Não use 5 V** — o módulo é 3,3 V                   |
| GND     | GND     |                                                     |
| L/R     | **GND** | GND = canal esquerdo. VDD = direito.                |
| WS      | GPIO25  | Word select (LRCLK)                                 |
| SCK     | GPIO26  | Bit clock (BCLK)                                    |
| SD      | GPIO33  | Dados (serial data out do mic)                      |

> ⚠️ **Armadilha nº 1 do INMP441.** O pino L/R define em qual metade do frame I2S o
> mic fala. Se ele está em GND, o firmware precisa ler o slot **esquerdo**; se está
> em VDD, o **direito**. Descasar os dois é a causa de "só sai zero" ou "só sai
> ruído branco" em 90% dos casos. O lado do firmware fica em
> `params.json → i2s.channel`.

Para trocar qualquer pino, edite `params.json` e rode `python3 tools/gen_config.py`.

## Parâmetros

`params.json` na raiz é a **fonte da verdade** de todo parâmetro de DSP, pinagem e
baud rate. O firmware não lê JSON: `tools/gen_config.py` traduz o arquivo para
`firmware/include/config.h` e `firmware/sdkconfig.defaults`. Os scripts Python leem
o `params.json` diretamente. Nenhum número é duplicado à mão.

```bash
python3 tools/gen_config.py    # rode sempre que mexer no params.json
```

## Build e flash

O projeto usa PlatformIO com o framework ESP-IDF.

```bash
python3 -m venv .venv-pio
.venv-pio/bin/pip install platformio

cd firmware
../.venv-pio/bin/pio run              # compila
../.venv-pio/bin/pio run -t upload    # grava no ESP32
../.venv-pio/bin/pio device monitor   # serial a 921600 baud
```

## Estado atual

**Batch 3 — feature extraction real.** O pipeline de concorrência é o definitivo
desde o Batch 2: os batches seguintes trocam o *algoritmo* dentro das tasks, não a
estrutura.

```
task_capture  (prio 6, core 1)   I2S ──▶ pool de 4 buffers
     │  q_audio      prof. 4, carrega o índice do buffer
     │  sem_free_buffers (contador, 0..4)
     ▼
task_features (prio 4, core 1)   pool ──▶ feature_frame_t
     │  q_features   prof. 8, carrega a struct por valor
     ▼
task_detect   (prio 3, core 0)   threshold ──▶ LED
```

`mtx_stats` protege `frames_captured`, `frames_dropped` e `anomalies_detected`.

### As 15 features

| Índice | Feature | Como |
|---|---|---|
| `f[0]` | RMS | direto do sinal no tempo |
| `f[1]` | Spectral Centroid | média das frequências ponderada pela magnitude |
| `f[2..14]` | 13 MFCCs | 20 filtros mel (80–7800 Hz) → log → DCT-II ortonormal |

Janela de Hann **periódica**, FFT complexa de 1024 pontos via `esp-dsp`, energias
mel sobre o espectro de **potência** com **log natural**, DCT-II na convenção
`norm='ortho'`. Essas quatro convenções são as que o `tools/dashboard/dsp.py` do
Batch 4 tem que copiar — divergir em qualquer uma faz o espectrograma do Python
não bater com o do C.

### Validação do DSP sem hardware

`tests/host/` compila o `firmware/src/features.c` **no PC**, sem alterar uma linha
dele: os stubs em `tests/host/stubs/` cobrem o que é do ESP32, com uma DFT ingênua
no lugar da FFT do `esp-dsp`. O resultado é comparado contra `librosa` + `scipy`.

```bash
python3 -m venv .venv && .venv/bin/pip install -r model/requirements.txt
.venv/bin/python tests/host/validate_dsp.py
```

Valida o código **nosso** — magnitude, centroide, filterbank mel, log e DCT.
**Não** valida a chamada ao `esp-dsp` em si (se `dsps_fft2r_fc32` + `dsps_bit_rev_fc32`
realmente deixam o resultado em ordem natural); isso só o hardware diz.

A comparação é feita relativa ao RMS do vetor de features, não elemento a elemento.
Num tom puro, 18 dos 20 filtros mel ficam grudados no piso `log(1e-10)`, onde o
log amplifica ruído de `float32` e MFCC nenhum é reprodutível — nenhum microfone
entrega isso. Nos sinais com piso de ruído realista, C e Python concordam em ~1e-6.

### Modo dataset

`params.json → modes.dataset = 1` faz o serial cuspir CSV puro, uma linha por
frame, sem nenhum log misturado — é o que o `collect.py` do Batch 5 consome.

```
rms,centroid,mfcc0,mfcc1,...,mfcc12
0.001832,1043.27,-8.4213,1.2044,...
```

Saída esperada no serial:

```
STATS captured=4688 dropped=0 anomalies=12 q_audio=0/4 q_features=0/8 lat_media_us=1180 lat_max_us=3402 uptime_s=300
ANOMALIA seq=1204 rms=0.183422 limiar=0.050000 lat_us=1402
```

### Critério de sucesso

1. Rodar 5 minutos contínuos com `dropped=0`.
2. Forçar um descarte e confirmar que o contador sobe **e a captura não para**.
   Não edite código C — mexa no `params.json`:

   ```jsonc
   "force_delay_detect_ms": 200     // trava a detecção → enche a q_features
   "force_delay_features_ms": 200   // trava a extração  → esgota o pool
   ```

   ```bash
   python3 tools/gen_config.py && cd firmware && ../.venv-pio/bin/pio run -t upload
   ```

   Atrasar a **detecção** derruba frames na `q_features`; atrasar as **features**
   derruba na captura, por falta de buffer livre. Os dois casos imprimem a etapa
   que descartou (`DROP features` / `DROP captura`). Guarde essa saída — vira
   seção do relatório.

Volte os dois para `0` depois do teste.
