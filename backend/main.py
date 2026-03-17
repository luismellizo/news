import asyncio
import logging
from typing import List
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from backend.config import config
from backend.store import STORE
from backend.scrapers.finnhub_ws import finnhub_websocket
from backend.scrapers.farside_etf import scraper_btc_etf_inflows
from backend.scrapers.yields import scraper_yields
from backend.scrapers.correlations import calcular_correlaciones
from backend.scrapers.macro_news import fetch_macro_noticias
from backend.scrapers.hormuz_strait import scraper_ormuz
from backend.alerter import loop_alertas

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler("bloomberg_backend.log", encoding="utf-8"), logging.StreamHandler()]
)

def _obtener_cierres_iniciales():
    import requests
    api_key = config.get("finnhub_api_key", "")
    if not api_key or api_key == "TU_API_KEY_FINNHUB_AQUI": return
    
    simbolos = [config["simbolos"]["spx_proxy"], config["simbolos"]["oil_proxy"], config["simbolos"]["btc"]]
    for s in simbolos:
        try:
            url = f"https://finnhub.io/api/v1/quote?symbol={s}&token={api_key}"
            resp = requests.get(url, timeout=5)
            data = resp.json()
            if "pc" in data and data["pc"]:
                STORE.precios_cierre[s] = data["pc"]
                STORE.precios[s]["precio"] = data.get("c", 0)
                STORE.precios[s]["cambio_pct"] = round(data.get("dp", 0), 2)
        except Exception as e:
            logging.error(f"Error obteniendo cierre {s}: {e}")

class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        for connection in list(self.active_connections):
            try:
                await connection.send_json(message)
            except Exception:
                self.disconnect(connection)

manager = ConnectionManager()

app = FastAPI(title="MiBloombergEficaz Backend API Nivel Institucional")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

background_tasks = set()

@app.on_event("startup")
async def startup_event():
    _obtener_cierres_iniciales()
    
    tareas = [
        asyncio.create_task(finnhub_websocket()),
        asyncio.create_task(scraper_btc_etf_inflows()),
        asyncio.create_task(scraper_yields()),
        asyncio.create_task(calcular_correlaciones()),
        asyncio.create_task(fetch_macro_noticias()),
        asyncio.create_task(loop_alertas()),
    ]
    background_tasks.update(tareas)
    
    # Broadcast Loop independently
    asyncio.create_task(broadcast_state_loop())
    logging.info("🚀 Todos los servicios Quant iniciados en background.")

async def broadcast_state_loop():
    while True:
        payload = {
            "precios": STORE.precios,
            "btc_etf_inflows": STORE.btc_etf_inflows,
            "yields": STORE.yields,
            "correlaciones": STORE.correlaciones,
            "macro": STORE.macro,
            "ws_conectado": STORE.ws_conectado,
            "usando_fallback": STORE.usando_fallback
        }
        await manager.broadcast(payload)
        await asyncio.sleep(0.5)

@app.get("/api/search")
async def search_symbols(q: str):
    import requests
    api_key = config.get("finnhub_api_key", "")
    if not api_key or api_key == "TU_API_KEY_FINNHUB_AQUI":
        return {"error": "API Key de Finnhub faltante", "result": []}
    
    try:
        url = f"https://finnhub.io/api/v1/search?q={q}&token={api_key}"
        resp = requests.get(url, timeout=5)
        return resp.json()
    except Exception as e:
        return {"error": str(e), "result": []}

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    import json
    await manager.connect(websocket)
    logging.info("🔌 Cliente Institucional UI conectado al WS.")
    try:
        while True:
            data_str = await websocket.receive_text()
            try:
                msg = json.loads(data_str)
                if msg.get("action") == "subscribe" and "symbols" in msg:
                    # Inscribir simbolos al ws de finnhub
                    if STORE.ws_conectado and STORE.finnhub_ws_conn:
                        for s in msg["symbols"]:
                            if s not in STORE.precios:
                                # Fetch initial closing price
                                import requests
                                api_key = config.get("finnhub_api_key", "")
                                STORE.precios[s] = {"precio": 0.0, "cambio_pct": 0.0, "volumen": 0, "ts": ""}
                                if api_key and api_key != "TU_API_KEY_FINNHUB_AQUI":
                                    try:
                                        url = f"https://finnhub.io/api/v1/quote?symbol={s}&token={api_key}"
                                        resp = requests.get(url, timeout=5)
                                        data = resp.json()
                                        if "pc" in data and data["pc"]:
                                            STORE.precios_cierre[s] = data["pc"]
                                            STORE.precios[s]["precio"] = data.get("c", 0)
                                            STORE.precios[s]["cambio_pct"] = round(data.get("dp", 0), 2)
                                    except:
                                        pass
                                
                                # Send sub msg to Finnhub
                                await STORE.finnhub_ws_conn.send(json.dumps({"type": "subscribe", "symbol": s}))
            except json.JSONDecodeError:
                pass
    except WebSocketDisconnect:
        manager.disconnect(websocket)
        logging.info("🔌 Cliente Institucional UI desconectado.")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=True)
