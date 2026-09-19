# Detector de Anomalias Acústicas

Sistema embarcado em ESP32 que captura áudio por um microfone I²S, extrai
features espectrais em tempo real e sinaliza desvios do perfil acústico normal
do ambiente. Um autoencoder treinado apenas com som normal atribui a cada frame
um erro de reconstrução; o que destoa cruza o limiar e acende o LED.

Opcionalmente, o mesmo pipeline identifica músicas de um acervo embarcado, por
casamento de impressões digitais no estilo Shazam. Os dois detectores rodam no
mesmo frame, cada um com o próprio LED.

Relatório técnico em [`docs/relatorio.md`](docs/relatorio.md).

## Arquitetura

Três tarefas FreeRTOS, duas filas, um semáforo contador e um mutex. O pipeline
de concorrência é independente do algoritmo de detecção.

```
task_capture  (prio 6, core 1)   I²S ──▶ pool de 4 buffers
     │  q_audio      profundidade 4, carrega o índice do buffer
     │  sem_free_buffers (semáforo contador, 0…4)
     ▼
task_features (prio 4, core 1)   pool ──▶ 15 features por frame
     │  q_features   profundidade 8, struct por valor
     ▼
task_detect   (prio 3, core 0)   detecção ──▶ LEDs
```

Diagrama completo em [`docs/rtos_diagram.svg`](docs/rtos_diagram.svg).

Cada frame tem 1024 amostras a 16 kHz, ou 64 ms. As 15 features são RMS,
spectral centroid e 13 MFCCs. A latência ponta a ponta medida é de 3,21 ms,
equivalente a 5% do orçamento do frame.

## Hardware

- ESP32 DevKit v1 (`esp32dev`)
- Microfone INMP441 (MEMS, I²S)
- 2 LEDs com resistor de 220 Ω

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
     LED anomalia ──[220Ω]─────────────┤ GPIO5        │
      └───────────────────────────────┤ GND          │
     LED música ────[220Ω]─────────────┤ GPIO18       │
      └───────────────────────────────┤ GND          │
                                      └──────────────┘
```

| Pino | Ligação | Observação |
|---|---|---|
| VDD | 3V3 | Não use 5 V, o módulo é de 3,3 V |
| GND | GND | |
| L/R | GND | GND seleciona o canal esquerdo, VDD o direito |
| WS | GPIO25 | Word select |
| SCK | GPIO26 | Bit clock |
| SD | GPIO33 | Dados do microfone |

| LED | GPIO | Acende |
|---|---|---|
| Anomalia | 5 | 500 ms, enquanto durar o som anômalo |
| Música | 18 | 5 s a cada faixa identificada |

Os dois LEDs piscam três vezes no boot, como autoteste. Se não piscarem, o
problema está na ligação e não na detecção.

O pino L/R define em qual metade do frame I²S o microfone transmite, e o
firmware precisa ler o slot correspondente. Descasar os dois faz a captura
retornar apenas zeros. O lado do firmware fica em `params.json` → `i2s.channel`.

Para trocar qualquer pino, edite o `params.json` e rode
`python3 tools/gen_config.py`.

## Instalação

```bash
python3 -m venv .venv-pio && .venv-pio/bin/pip install platformio
python3 -m venv .venv     && .venv/bin/pip install -r model/requirements.txt
```

## Como rodar

### 1. Coletar o ambiente e treinar

O modelo aprende o perfil acústico do local onde será usado, então a coleta
precisa ser feita na sala da demonstração, com o microfone na posição
definitiva.

```bash
.venv/bin/python model/collect.py --minutos 10 --saida model/data/normal.csv
.venv/bin/python model/collect.py --guiado     --saida model/data/anomaly.csv
.venv/bin/python model/train.py
```

A primeira coleta é silenciosa, apenas o microfone gravando. A segunda dura um
minuto e exibe na tela a hora de bater palmas, assobiar, bater na mesa e falar.
O treino gera `model/anomaly_detector.onnx` e os pesos para o firmware.

### 2. Gravar o firmware

```bash
cd firmware
../.venv-pio/bin/pio run -t upload
```

### 3. Ver funcionando

```bash
.venv/bin/python tools/monitor.py
```

O monitor exibe uma linha que se reescreve, com o score de anomalia contra o
limiar, o RMS atual e os contadores. Cada evento imprime uma linha permanente.

```
▁▁▂▁▁▂▁▁▁▂▁▁▁▁▂  anom   0.31/1.00  votos   4/60  rms 0.0031  0a 0m  02:14
  ANOMALIA  23:51:12  score   4.821 =   4.8x o limiar  ·  latencia 3.21 ms
```

Bata uma palma perto do microfone e o LED de anomalia acende.

## Identificação de músicas

Coloque os arquivos de áudio em `music_id/songs/`, gere o banco e ligue o modo:

```bash
.venv/bin/python music_id/build_db.py --testar
# params.json → modes.music_id = 1
python3 tools/gen_config.py
cd firmware && ../.venv-pio/bin/pio run -t upload
```

O monitor lista as faixas ao abrir e anuncia cada identificação:

```
♪ Radio/Video  System of a Down  ·  08:56:07  ·  41 votos
```

O LED verde fica aceso por 5 s. O nome vem de `music_id/songs.json`, gerado
junto com o banco, já que o firmware transmite apenas o índice.

## Testes

Cada bloco de processamento tem um par em C e em Python, com um teste que
comprova a concordância entre os dois. Todos rodam sem hardware.

```bash
.venv/bin/python tests/host/validate_dsp.py     # features em C vs librosa
.venv/bin/python tests/host/validate_model.py   # inferência em C vs o .onnx
.venv/bin/python tests/host/validate_peaks.py   # peak picking em C vs Python
.venv/bin/python tests/host/validate_match.py   # casamento em C vs Python
```

Análise de latência a partir do log do firmware:

```bash
.venv/bin/python tests/latency_analysis.py --serial --segundos 120
```

## Parâmetros

Todo parâmetro de DSP, pinagem e RTOS vive em `params.json`. O firmware não lê
JSON: `tools/gen_config.py` o traduz para `firmware/include/config.h`, enquanto
os scripts Python leem o arquivo diretamente. Nenhum número é duplicado à mão
entre os dois lados.

```bash
python3 tools/gen_config.py   # rode sempre que alterar o params.json
```
