#!/usr/bin/env python3
"""Ponte serial -> WebSocket pro dashboard.

    ESP32 --serial 921600--> server.py --WebSocket--> index.html

O ESP32 nao tem WiFi por decisao de projeto. Quem fala com o browser e este
processo aqui no PC.

    .venv/bin/python tools/dashboard/server.py [--port /dev/ttyUSB0]
    http://localhost:8000
"""
import argparse
import asyncio
import csv
import glob
import io
import json
import queue
import sys
import threading
import time
from collections import deque
from pathlib import Path

import serial
import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dsp  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
P = json.loads((ROOT / "params.json").read_text())
BAUD = P["serial"]["baud"]
N_MFCC = P["n_mfcc"]
N_BANDS = P["n_bands"]

# ~15,6 fps; 120 s de historico cabem folgado e cobrem o botao de gravar.
HISTORICO = deque(maxlen=2000)

_fila: "queue.Queue[dict]" = queue.Queue(maxsize=256)
_clientes: set[WebSocket] = set()
_ultimo_erro = {"msg": None}

CAMPOS = ["t_us", "rms", "centroid", "score"]


def acha_porta() -> str | None:
    portas = sorted(glob.glob("/dev/ttyUSB*") + glob.glob("/dev/ttyACM*"))
    return portas[0] if portas else None


def parse(linha: str) -> dict | None:
    """S,<t_us>,<rms>,<centroid>,<score>,<threshold>,<13 mfccs>,<64 bandas>"""
    p = linha.split(",")
    esperado = 6 + N_MFCC + N_BANDS
    if len(p) != esperado or p[0] != "S":
        return None
    try:
        return {
            "t_us": int(p[1]),
            "rms": float(p[2]),
            "centroid": float(p[3]),
            "score": float(p[4]),
            "threshold": float(p[5]),
            "mfcc": [float(v) for v in p[6:6 + N_MFCC]],
            "bands": [int(v) for v in p[6 + N_MFCC:]],
        }
    except ValueError:
        return None


def le_serial(porta: str) -> None:
    """Thread. Reconecta sozinha: desplugar a placa nao pode derrubar o server."""
    while True:
        try:
            with serial.Serial(porta, BAUD, timeout=1) as ser:
                _ultimo_erro["msg"] = None
                print(f"serial conectada: {porta} @ {BAUD}", flush=True)
                while True:
                    linha = ser.readline().decode("utf-8", "replace").strip()
                    if not linha:
                        continue
                    if not linha.startswith("S,"):
                        print(linha, flush=True)   # log do firmware passa direto
                        continue
                    frame = parse(linha)
                    if frame is None:
                        continue
                    HISTORICO.append(frame)
                    try:
                        _fila.put_nowait(frame)
                    except queue.Full:
                        pass   # browser lento nao pode segurar a leitura serial
        except serial.SerialException as e:
            _ultimo_erro["msg"] = str(e)
            print(f"serial caiu ({e}); tentando de novo em 2 s", flush=True)
            time.sleep(2)


async def bombeia() -> None:
    """Drena a fila da thread serial e reemite pros browsers conectados."""
    loop = asyncio.get_running_loop()
    while True:
        frame = await loop.run_in_executor(None, _fila.get)
        for ws in list(_clientes):
            try:
                await ws.send_json(frame)
            except Exception:
                _clientes.discard(ws)


@asynccontextmanager
async def lifespan(app: FastAPI):
    tarefa = asyncio.create_task(bombeia())
    yield
    tarefa.cancel()


app = FastAPI(lifespan=lifespan)


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(Path(__file__).parent / "index.html")


@app.get("/params")
async def params() -> JSONResponse:
    """O browser pega daqui o threshold e as frequencias das bandas — assim o
    params.json continua sendo a unica fonte da verdade."""
    return JSONResponse({
        **P,
        "band_freqs": dsp.band_freqs().round(1).tolist(),
        "serial_erro": _ultimo_erro["msg"],
    })


@app.websocket("/ws")
async def ws_frames(ws: WebSocket) -> None:
    await ws.accept()
    _clientes.add(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        _clientes.discard(ws)


@app.post("/upload")
async def upload(file: UploadFile) -> JSONResponse:
    """Processa um WAV/MP3 com o MESMO pipeline do firmware. Tocar o arquivo no
    alto-falante e capturar pelo mic deve dar dois espectrogramas parecidos —
    e assim que se valida que o C e o Python concordam."""
    tmp = Path("/tmp") / f"upload_{int(time.time())}_{file.filename}"
    tmp.write_bytes(await file.read())
    try:
        return JSONResponse(dsp.spectrogram(tmp))
    finally:
        tmp.unlink(missing_ok=True)


@app.post("/record")
async def record(segundos: float = 10.0) -> PlainTextResponse:
    """Ultimos N segundos de features em CSV, mesmas colunas do MODE_DATASET."""
    if not HISTORICO:
        return PlainTextResponse("sem dados", status_code=503)

    corte = HISTORICO[-1]["t_us"] - segundos * 1e6
    linhas = [f for f in HISTORICO if f["t_us"] >= corte]

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["rms", "centroid"] + [f"mfcc{i}" for i in range(N_MFCC)])
    for f in linhas:
        w.writerow([f"{f['rms']:.6f}", f"{f['centroid']:.2f}"] +
                   [f"{v:.4f}" for v in f["mfcc"]])

    nome = f"clip_{int(time.time())}.csv"
    return PlainTextResponse(buf.getvalue(), headers={
        "Content-Disposition": f'attachment; filename="{nome}"'})


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default=None, help="porta serial (padrao: autodetecta)")
    ap.add_argument("--http-port", type=int, default=8000)
    args = ap.parse_args()

    porta = args.port or acha_porta()
    if porta:
        threading.Thread(target=le_serial, args=(porta,), daemon=True).start()
    else:
        # Sem placa o dashboard ainda serve pra analisar arquivo por upload.
        _ultimo_erro["msg"] = "nenhuma porta serial encontrada"
        print("nenhuma /dev/ttyUSB* ou /dev/ttyACM*; so o upload vai funcionar",
              flush=True)

    uvicorn.run(app, host="127.0.0.1", port=args.http_port, log_level="warning")


if __name__ == "__main__":
    main()
