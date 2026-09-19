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
     LED anomalia ──[220Ω]─────────── ┤ GPIO5        │
      └──────────────────────────────┤ GND          │
     LED música (verde) ──[220Ω]───── ┤ GPIO18       │
      └──────────────────────────────┤ GND          │
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

Os dois LEDs vão do GPIO ao GND, cada um com resistor de 220 Ω em série. A
perna longa (anodo) fica no lado do resistor.

| LED | GPIO | Quando acende |
|-----|------|---------------|
| Anomalia | GPIO5 | 500 ms a cada anomalia detectada |
| Música (verde) | GPIO18 | 5 s a cada música identificada |

Os dois piscam 3 vezes no boot, como autoteste — se não piscarem, o problema é
de ligação, não de detecção.

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

## Arquitetura

O pipeline de concorrência é independente do algoritmo: as tasks, filas,
semáforo e mutex são os mesmos para a detecção de anomalia e para a
identificação de música.

```
task_capture  (prio 6, core 1)   I2S ──▶ pool de 4 buffers
     │  q_audio      prof. 4, carrega o índice do buffer
     │  sem_free_buffers (contador, 0..4)
     ▼
task_features (prio 4, core 1)   pool ──▶ feature_frame_t
     │  q_features   prof. 8, carrega a struct por valor
     ▼
task_detect   (prio 3, core 0)   detecção ──▶ LEDs
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
`norm='ortho'`. Essas quatro convenções são as que o `tools/dashboard/dsp.py`
replica — divergir em qualquer uma faz o espectrograma do Python não bater com
o do C.

## Modelo

```bash
.venv/bin/python model/collect.py --minutos 10 --saida model/data/normal.csv
.venv/bin/python model/collect.py --minutos 1  --saida model/data/anomaly.csv
.venv/bin/python model/train.py
```

O autoencoder 15→8→4→8→15 treina **só com som normal**. O score é o erro de
reconstrução: o que ele nunca viu, reconstrói mal. `train.py` gera dois
artefatos — `model/anomaly_detector.onnx` (entregável, com a normalização
embutida e pesos incorporados) e `firmware/include/model_weights.h`.

O threshold sai do percentil 99 de um conjunto de validação **separado do
treino**. Calculá-lo sobre os dados que o treino viu daria um número otimista,
e você descobriria isso na demonstração.

O modelo versionado foi treinado com **áudio real** — 20,6 min de ambiente em
dois estados térmicos da máquina e 48 s de anomalias (palmas, assobio, batidas,
fala), tudo pelo mesmo microfone e na mesma sala. O cabeçalho do
`model_weights.h` registra a procedência.

Resultado por janela de ~1 s: **acurácia 99,65%**, falso positivo 0,41%,
detecção 100,00%. Detalhes e ressalvas em [`docs/relatorio.md`](docs/relatorio.md).

Para coletar as anomalias com roteiro na tela:

```bash
.venv/bin/python model/collect.py --guiado --saida model/data/anomaly.csv
```

No device, `detector.c` faz as quatro matmuls em C puro sobre pesos em
`.rodata` — sem TFLite, sem runtime externo, sem quantização. Um alerta exige
`debounce_n` frames anômalos consecutivos, o que corta quase todo falso
positivo isolado ao custo de `debounce_n × 64 ms` de latência.

### Validação sem hardware

`tests/host/` compila o `firmware/src/features.c` **no PC**, sem alterar uma linha
dele: os stubs em `tests/host/stubs/` cobrem o que é do ESP32, com uma DFT ingênua
no lugar da FFT do `esp-dsp`. O resultado é comparado contra `librosa` + `scipy`.

```bash
python3 -m venv .venv && .venv/bin/pip install -r model/requirements.txt
.venv/bin/python tests/host/validate_dsp.py     # features.c  vs librosa/scipy
.venv/bin/python tests/host/validate_model.py   # detector.c  vs o .onnx
```

`validate_model.py` roda os mesmos frames pelas quatro matmuls em C e pelo
modelo treinado. Erro relativo típico de 1e-7 — arredondamento de `float32` e
nada mais. Se a inferência do device divergir do modelo, aparece aqui e não na
demonstração.

Valida o código **nosso** — magnitude, centroide, filterbank mel, log e DCT.
**Não** valida a chamada ao `esp-dsp` em si (se `dsps_fft2r_fc32` + `dsps_bit_rev_fc32`
realmente deixam o resultado em ordem natural); isso só o hardware diz.

A comparação é feita relativa ao RMS do vetor de features, não elemento a elemento.
Num tom puro, 18 dos 20 filtros mel ficam grudados no piso `log(1e-10)`, onde o
log amplifica ruído de `float32` e MFCC nenhum é reprodutível — nenhum microfone
entrega isso. Nos sinais com piso de ruído realista, C e Python concordam em ~1e-6.

## Identificação de músicas

Com `modes.music_id = 1` a Task 3 roda **dois detectores no mesmo frame**: o
autoencoder de anomalia e um casamento de fingerprint estilo Shazam contra um
banco embarcado. Cada um acende seu próprio LED. Cabem juntos com folga — o
autoencoder custa 0,17 ms e o casamento 46 µs, contra 64 ms de orçamento.

**A arquitetura RTOS não muda** — mesmas três tasks, mesmas filas, mesmo
semáforo, mesmo mutex. Muda só o que roda dentro das Tasks 2 e 3.

```bash
# 1. coloque os arquivos de áudio em music_id/songs/
# 2. gere o banco (recorta 30 s de maior energia de cada faixa)
.venv/bin/python music_id/build_db.py --testar
# 3. ligue o modo e grave
#    params.json -> modes.music_id = 1
python3 tools/gen_config.py
cd firmware && ../.venv-pio/bin/pio run -t upload
# 4. monitore
.venv/bin/python tools/monitor.py
```

O monitor lista as faixas no início e anuncia cada identificação:

```
♪ Radio/Video  System of a Down  ·  08:56:07  ·  41 votos  ·  5 piscadas no LED
```

O LED verde do GPIO18 fica aceso por 5 s. Qual música é você lê no terminal:
sem WiFi, o índice vai pelo serial e o nome vem do `music_id/songs.json`,
gerado junto com o banco.

### Como funciona

| Etapa | |
|---|---|
| Peak picking | pico mais forte de cada uma das 6 super-bandas, sobre **256** bandas log, acima da média do frame + margem — tudo em aritmética inteira |
| Hash | 21 bits: `f1(8) \| f2(8) \| Δt(5)`, cada âncora pareada com os 3 picos seguintes em até 2 s |
| Banco | `uint64` ordenado, busca binária, gerado em 2 fases deslocadas |
| Votação | histograma `[música][offset circular]`, dispara ao cruzar os votos mínimos **e** bater o segundo colocado por 1,5× |

## Rodar e ver funcionando

```bash
.venv/bin/python tools/monitor.py
```

Monitor ao vivo no terminal: sparkline dos últimos ~3,5 s do score em escala log
relativa ao threshold (verde abaixo, vermelho acima), valores atuais e contador
de alertas. Cada anomalia imprime uma linha permanente:

```
▁▁▂▁▁▂▁▁▁▂▁▁▁▁▂▁▁▁  score  0.312/0.998  rms 0.0031  cent  941Hz  3 alertas  02:14
  ANOMALIA  23:51:12  score   4.821 =   4.8x o limiar  ·  rms 0.0421  centroide 1180 Hz  ·  latencia 3.21 ms
```

Se o ambiente ficar permanentemente acima do limiar, ele avisa:
`MODELO DESATUALIZADO PARA ESTE AMBIENTE — recolete e retreine`. Isso importa
porque o alerta dispara **uma vez** e só rearma quando o score volta abaixo do
threshold — um modelo saturado parece parado, não parece quebrado.

### Recalibrar para um ambiente novo

O perfil normal precisa cobrir as condições de operação. Num ambiente diferente
daquele onde o modelo foi treinado, refaça:

```bash
.venv/bin/python model/collect.py --minutos 10 --saida model/data/normal.csv
.venv/bin/python model/collect.py --guiado  --saida model/data/anomaly.csv
.venv/bin/python model/train.py
cd firmware && ../.venv-pio/bin/pio run -t upload
```

## Dashboard

O ESP32 não tem WiFi por decisão de projeto. Ele emite um frame compacto pelo
serial e um servidor Python no PC reempacota pro browser:

```
ESP32 --serial 921600--> server.py --WebSocket--> index.html (canvas)
```

```bash
.venv/bin/python tools/dashboard/server.py     # autodetecta /dev/ttyUSB*
# http://localhost:8000
```

Uma linha de texto por frame, `S,<t_us>,<rms>,<centroid>,<score>,<13 mfccs>,<64 bandas>`
— cerca de 420 bytes, ~6,5 KB/s num canal de 92 KB/s. As 64 bandas são o espectro
comprimido em escala log entre `fmin` e `fmax`, cada uma em dBFS mapeado para
`uint8`. O espectro cru de 513 bins e o áudio bruto não cabem no serial.

O dashboard tem quatro coisas:

1. **Espectrograma ao vivo** — waterfall com colormap magma, eixo Y em log (as
   bandas já são log-espaçadas, então índice linear já é escala log).
2. **Score de anomalia** — linha do tempo com o threshold desenhado e os pontos
   que cruzaram marcados.
3. **Upload de arquivo** — o servidor roda o **mesmo** `dsp.py` sobre o WAV/MP3.
   Toque o arquivo no alto-falante, capture pelo mic, compare os dois: é assim
   que se confirma que o pipeline do C e o do Python concordam.
4. **Overlay de picos** — máximos locais por cima do espectrograma. Não faz nada
   para a detecção de anomalia, mas é a ferramenta para calibrar o peak
   picking da identificação de música.

O botão **gravar 10 s → CSV** baixa as últimas features com as mesmas colunas do
modo dataset — serve pra clipe curto e dirigido. Coleta longa é o `collect.py`.

### Modo dataset

`params.json → modes.dataset = 1` faz o serial cuspir CSV puro, uma linha por
frame, sem nenhum log misturado — é o que o `collect.py` consome.

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
