import asyncio
import numpy as np
from datetime import datetime
import logging

from backend.store import STORE

logger = logging.getLogger("Bloomberg")

async def calcular_correlaciones():
    """Calcula coeficiente de correlación de Pearson en tiempo real sobre ventana histórica"""
    intervalo = 30  # Actualiza cada 30 segundos

    while True:
        try:
            spy_hist = STORE.historial_precios.get("SPY", [])
            btc_hist = STORE.historial_precios.get("BINANCE:BTCUSDT", [])
            uso_hist = STORE.historial_precios.get("USO", [])

            # Asegurar longitud igual cortando el mas largo
            min_len_spy_btc = min(len(spy_hist), len(btc_hist))
            if min_len_spy_btc > 10:
                s_arr = np.array(spy_hist[-min_len_spy_btc:])
                b_arr = np.array(btc_hist[-min_len_spy_btc:])
                
                # Pearson correl function returns matrix, take [0, 1] component
                if np.std(s_arr) > 0 and np.std(b_arr) > 0:
                    corr = np.corrcoef(s_arr, b_arr)[0, 1]
                    STORE.correlaciones["spy_btc_60m"] = round(float(corr), 2)

            min_len_spy_uso = min(len(spy_hist), len(uso_hist))
            if min_len_spy_uso > 10:
                s_arr = np.array(spy_hist[-min_len_spy_uso:])
                u_arr = np.array(uso_hist[-min_len_spy_uso:])
                if np.std(s_arr) > 0 and np.std(u_arr) > 0:
                    corr = np.corrcoef(s_arr, u_arr)[0, 1]
                    STORE.correlaciones["spy_uso_60m"] = round(float(corr), 2)

            STORE.correlaciones["ultima_actualizacion"] = datetime.now().strftime("%H:%M:%S")

        except Exception as e:
            logger.error(f"Error calculando correlaciones: {e}")

        await asyncio.sleep(intervalo)

async def correlate_with_volume(asset_ticker: str, news_timestamp: float) -> bool:
    """
    Compara el timestamp de una noticia con el pico de volumen en WS.
    Si el volumen del activo se disparó ANTES de procesar la noticia,
    marca la noticia como ALREADY_PRICED_IN.
    """
    try:
        precio_data = STORE.precios.get(asset_ticker)
        if not precio_data:
            return False
            
        current_ts = datetime.now(timezone.utc).timestamp()
        latency_seconds = current_ts - news_timestamp
        
        # Lógica Stub: Si la noticia tardó > 60s en procesarse por APIs
        # y el volumen actual es anormalmente alto, we assume it's priced in by HFT.
        if latency_seconds > 60 and precio_data["volumen"] > 0:
            return True
            
        return False
    except Exception as e:
        logger.error(f"Error validando correlación de volumen para {asset_ticker}: {e}")
        return False
