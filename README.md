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

**Batch 1 — scaffold + captura de áudio.** Uma única task lê frames de 1024
amostras (64 ms @ 16 kHz) pelo I2S e imprime o RMS no serial:

```
frame=142 rms=0.001832 dbfs=-54.7 leitura_us=64031
```

Critério de sucesso: RMS estável em silêncio e subindo ≥ 10× ao bater palma perto
do microfone.
