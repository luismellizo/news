import asyncio
import json
import logging
from datetime import datetime, timezone

from backend.config import config
from backend.store import STORE

logger = logging.getLogger("Bloomberg")

YFINANCE_DISPONIBLE = True
try:
    import yfinance as yf
except ImportError:
    YFINANCE_DISPONIBLE = False

async def finnhub_websocket():
    import websockets

    api_key = config.get("finnhub_api_key", "")
    if not api_key or api_key == "TU_API_KEY_FINNHUB_AQUI":
        logger.warning("No API key. Fallback yfinance.")
        STORE.usando_fallback = True
        return await _fallback_yfinance()

    url = f"wss://ws.finnhub.io?token={api_key}"
    simbolos = [
        config["simbolos"]["spx_proxy"],
        config["simbolos"]["btc"],
        config["simbolos"]["oil_proxy"],
    ]

    intentos = 0
    while intentos < 10:
        try:
            async with websockets.connect(url, ping_interval=30) as ws:
                STORE.ws_conectado = True
                STORE.usando_fallback = False
                STORE.finnhub_ws_conn = ws
                intentos = 0

                for s in simbolos:
                    await ws.send(json.dumps({"type": "subscribe", "symbol": s}))
                
                async for mensaje in ws:
                    try:
                        data = json.loads(mensaje)
                        if data.get("type") == "trade" and data.get("data"):
                            for trade in data["data"]:
                                simbolo = trade.get("s", "")
                                precio = trade.get("p", 0.0)
                                volumen = trade.get("v", 0)
                                ts = trade.get("t", 0)

                                if simbolo in STORE.precios:
                                    cierre = STORE.precios_cierre.get(simbolo, precio)
                                    cambio = ((precio - cierre) / cierre * 100) if cierre else 0

                                    STORE.precios[simbolo] = {
                                        "precio": round(precio, 2),
                                        "cambio_pct": round(cambio, 2),
                                        "volumen": volumen,
                                        "ts": datetime.fromtimestamp(ts / 1000, tz=timezone.utc).strftime("%H:%M:%S") if ts else ""
                                    }

                                    hist = STORE.historial_precios.get(simbolo, [])
                                    hist.append(precio)
                                    if len(hist) > 60: hist = hist[-60:]
                                    STORE.historial_precios[simbolo] = hist

                    except Exception as e:
                        pass
        except Exception as e:
            STORE.ws_conectado = False
            intentos += 1
            await asyncio.sleep(min(2 ** intentos, 60))

    STORE.usando_fallback = True
    await _fallback_yfinance()

async def _fallback_yfinance():
    if not YFINANCE_DISPONIBLE: return
    simbolos = {
        config["simbolos"]["spx_proxy"]: config["simbolos"]["spx_proxy"],
        "BTC-USD": config["simbolos"]["btc"],
        config["simbolos"]["oil_proxy"]: config["simbolos"]["oil_proxy"],
    }
    
    while True:
        try:
            for yf_sym, store_key in simbolos.items():
                ticker = yf.Ticker(yf_sym)
                info = ticker.fast_info
                precio = getattr(info, "last_price", 0) or 0
                cierre = getattr(info, "previous_close", precio) or precio
                cambio = ((precio - cierre) / cierre * 100) if cierre else 0

                if store_key in STORE.precios:
                    STORE.precios[store_key] = {
                        "precio": round(precio, 2),
                        "cambio_pct": round(cambio, 2),
                        "volumen": 0,
                        "ts": datetime.now().strftime("%H:%M:%S")
                    }
                    hist = STORE.historial_precios.get(store_key, [])
                    hist.append(precio)
                    if len(hist) > 60: hist = hist[-60:]
                    STORE.historial_precios[store_key] = hist
        except: pass
        await asyncio.sleep(5)
