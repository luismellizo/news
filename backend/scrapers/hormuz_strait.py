import asyncio
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import logging
from pydantic import BaseModel, Field, ValidationError

from backend.config import config
from backend.store import STORE

logger = logging.getLogger("Bloomberg")

class HormuzStatus(BaseModel):
    estado: str = Field(..., description="Must be 'Restricted' or 'Normal'")
    transitos_24h: int = Field(..., description="Number of ships transiting in 24h")
    tanqueros_esperando: int = Field(..., description="Number of tankers waiting")
    trafico_caido_pct: float = Field(..., description="Percentage of traffic dropped")

async def extract_hormuz_data_llm(html_text: str) -> HormuzStatus:
    """
    Placeholder for LLM Extraction (Reemplaza las RegEx frágiles).
    Takes clean HTML raw text and strictly outputs a HormuzStatus JSON.
    """
    try:
        # Aquí se inyectaría ChatGPT/Gemini para que lea el texto crudo 
        # y devuelva los enteros inferidos por estructura Pydantic. 
        texto = html_text.lower()
        if "restricted" in texto or "closure" in texto:
            estado = "🔴 RESTRICTED"
        else:
            estado = "🟢 NORMAL"
            
        import re
        trans, tank, pct = 0, 0, 0.0
        # Mantenemos esto temporalmente solo para que el mock funcione sin la API AI de pago
        m_t = re.search(r'(\d+)\s*(?:transit|passage|ship)', texto)
        if m_t: trans = int(m_t.group(1))
        m_tk = re.search(r'(\d+)\s*(?:tanker|waiting|queue)', texto)
        if m_tk: tank = int(m_tk.group(1))
        m_p = re.search(r'(\d+\.?\d*)\s*%', texto)
        if m_p: pct = float(m_p.group(1))

        # This simulates the LLM returning structured data (validated automatically by Pydantic)
        return HormuzStatus(
            estado=estado,
            transitos_24h=trans,
            tanqueros_esperando=tank,
            trafico_caido_pct=pct
        )
    except Exception as e:
        raise ValueError("Error durante la extracción estructurada del LLM sobre el HTML.")

async def scraper_ormuz():
    delay = config.get("scraper_delay_segundos", 2)
    intervalo = config.get("refresh_ormuz_minutos", 3) * 60

    if not hasattr(STORE, "ormuz"):
        STORE.ormuz = {
            "estado": "🟡 INIT",
            "transitos_24h": 0,
            "tanqueros_esperando": 0,
            "trafico_caido_pct": 0.0,
            "ultima_actualizacion": "Sin datos",
            "error": "",
            "transitos_anterior": 0
        }

    while True:
        try:
            await asyncio.sleep(delay)
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

            loop = asyncio.get_event_loop()
            resp = await loop.run_in_executor(None, lambda: requests.get("https://hormuzstraitmonitor.com/", headers=headers, timeout=15))

            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "lxml")
                texto_completo = soup.get_text(separator=" ")

                try:
                    # Pase por Pydantic/LLM garantizando contrato estricto
                    datos_estructurados = await extract_hormuz_data_llm(texto_completo)
                    
                    anterior = STORE.ormuz.get("transitos_anterior", 0)
                    STORE.ormuz = {
                        "estado": datos_estructurados.estado,
                        "transitos_24h": datos_estructurados.transitos_24h,
                        "tanqueros_esperando": datos_estructurados.tanqueros_esperando,
                        "trafico_caido_pct": datos_estructurados.trafico_caido_pct,
                        "ultima_actualizacion": datetime.now().strftime("%H:%M:%S"),
                        "error": "",
                        "transitos_anterior": anterior if anterior else datos_estructurados.transitos_24h
                    }
                except ValidationError as ve:
                    logger.critical(f"Validación de datos falló estructurando Ormuz: {ve}. DOM cambiado?")
                    STORE.ormuz["error"] = "Error formato de datos - DOM obsoleto."
                    if "STALE" not in STORE.ormuz.get("estado", ""):
                        STORE.ormuz["estado"] = "⚪ STALE"

            else:
                logger.error(f"Error HTTP leyendo Hormuz: HTTP {resp.status_code}")
                STORE.ormuz["error"] = f"HTTP {resp.status_code}"
                if "STALE" not in STORE.ormuz.get("estado", ""):
                    STORE.ormuz["estado"] = "⚪ STALE"

        except requests.exceptions.ConnectionError:
            logger.error("Monitor inalcanzable temporalmente.")
            STORE.ormuz["error"] = "Red inalcanzable"
            if "STALE" not in STORE.ormuz.get("estado", ""):
                STORE.ormuz["estado"] = "⚪ STALE"
        except Exception as e:
            logger.error(f"Fallo grave Hormuz: {str(e)}")
            STORE.ormuz["error"] = str(e)[:50]
            if "STALE" not in STORE.ormuz.get("estado", ""):
                STORE.ormuz["estado"] = "⚪ STALE"

        await asyncio.sleep(intervalo)
