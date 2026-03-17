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
