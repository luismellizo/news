import asyncio
from datetime import datetime
import logging

from backend.store import STORE

logger = logging.getLogger("Bloomberg")

YFINANCE_DISPONIBLE = True
try:
    import yfinance as yf
except ImportError:
    YFINANCE_DISPONIBLE = False

async def scraper_yields():
    """
    Scraper para datos institucionales: 10-Year Treasury Note Yield (^TNX)
    Los traders institucionales siempre observan la renta fija.
    """
    if not YFINANCE_DISPONIBLE:
        logger.warning("yfinance no disponible para Yields.")
        return

    intervalo = 300  # 5 minutos

    while True:
        try:
            ticker = yf.Ticker("^TNX")
            info = ticker.fast_info
            
            precio = getattr(info, "last_price", 0) or 0
            cierre = getattr(info, "previous_close", precio) or precio
            cambio = ((precio - cierre) / cierre * 100) if cierre else 0

            if precio > 0:
                STORE.yields["TNX"] = {
                    "valor": round(precio, 3), # Yield in %
                    "cambio_bps": round((precio - cierre) * 100, 1), # Basis points
                    "cambio_pct": round(cambio, 2),
                    "ultima_actualizacion": datetime.now().strftime("%H:%M:%S"),
                    "error": ""
                }
        except Exception as e:
            STORE.yields["TNX"]["error"] = str(e)[:50]
            
        await asyncio.sleep(intervalo)
