import asyncio
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import logging
from pydantic import BaseModel, Field, ValidationError
import instructor
from openai import AsyncOpenAI

from backend.config import config
from backend.store import STORE

logger = logging.getLogger("Bloomberg")

# Definición del esquema estricto para monitoreo marítimo
class HormuzStatus(BaseModel):
    estado: str = Field(..., description="Current status of the Strait of Hormuz. Must be either 'Restricted' or 'Normal'")
    transitos_24h: int = Field(..., description="Exact number of ships that transited the strait in the last 24 hours. Extract from text.")
    tanqueros_esperando: int = Field(..., description="Exact number of tankers waiting or in queue. Extract from text.")
    trafico_caido_pct: float = Field(..., description="Percentage drop in traffic relative to historical averages. If no drop is mentioned, extract as 0.0")

# Cliente OpenAI con Instructor para extracción estructurada
client = instructor.from_openai(AsyncOpenAI())

async def extract_hormuz_data_llm(html_text: str) -> HormuzStatus:
    """
    Extracción REAL asíncrona usando IA.
    CERO REGEX. El LLM lee el texto crudo y genera el objeto HormuzStatus validado por Pydantic.
    """
    try:
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            response_model=HormuzStatus,
            messages=[
                {
                    "role": "system", 
                    "content": "You are a quantitative data extractor for maritime traffic. Extract structured data from the provided monitor text."
                },
                {
                    "role": "user", 
                    "content": f"Extract metrics from this data source:\n\n{html_text[:5000]}"
                }
            ],
            temperature=0,
        )
        return response
    except Exception as e:
        logger.error(f"Falla crítica en extracción IA de Hormuz: {e}")
        raise ValueError(f"Falla de API OpenAI: {e}")

async def scraper_ormuz():
    delay = config.get("scraper_delay_segundos", 2)
    intervalo = config.get("refresh_ormuz_minutos", 3) * 60

    # Asegurar inicialización en el store si no existe
    if not hasattr(STORE, "ormuz") or not STORE.ormuz:
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
            # Simulación de navegador legítimo para evitar bloqueos básicos
            headers = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"}

            loop = asyncio.get_event_loop()
            resp = await loop.run_in_executor(None, lambda: requests.get("https://hormuzstraitmonitor.com/", headers=headers, timeout=15))

            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "lxml")
                
                # Extraemos el texto del body para enviárselo al LLM
                body = soup.find('body')
                texto_crudo = body.get_text(separator=" ", strip=True) if body else soup.get_text(separator=" ", strip=True)

                try:
                    # Llamada a la IA REAL con Instructor
                    datos_estructurados = await extract_hormuz_data_llm(texto_crudo)
                    
                    # Formateo visual para el frontend según el estado extraído por la IA
                    estado_fmt = "🔴 RESTRICTED" if "restrict" in datos_estructurados.estado.lower() else "🟢 NORMAL"

                    anterior = STORE.ormuz.get("transitos_anterior", 0)
                    STORE.ormuz = {
                        "estado": estado_fmt,
                        "transitos_24h": datos_estructurados.transitos_24h,
                        "tanqueros_esperando": datos_estructurados.tanqueros_esperando,
                        "trafico_caido_pct": datos_estructurados.trafico_caido_pct,
                        "ultima_actualizacion": datetime.now().strftime("%H:%M:%S"),
                        "error": "",
                        "transitos_anterior": anterior if anterior else datos_estructurados.transitos_24h
                    }
                except ValidationError as ve:
                    logger.error(f"Error de validación Pydantic tras respuesta IA: {ve}")
                    STORE.ormuz["error"] = "Error validación IA"
                    if "STALE" not in str(STORE.ormuz.get("estado", "")):
                        STORE.ormuz["estado"] = "⚪ STALE"
                except Exception as ex:
                    logger.error(f"Error procesando IA en Ormuz: {ex}")
                    STORE.ormuz["error"] = "Fallo IA"
                    if "STALE" not in str(STORE.ormuz.get("estado", "")):
                        STORE.ormuz["estado"] = "⚪ STALE"

            else:
                logger.error(f"Error HTTP en Hormuz: {resp.status_code}")
                STORE.ormuz["error"] = f"HTTP {resp.status_code}"
                if "STALE" not in str(STORE.ormuz.get("estado", "")):
                    STORE.ormuz["estado"] = "⚪ STALE"

        except Exception as e:
            logger.error(f"Excepción en scraper Ormuz: {e}")
            STORE.ormuz["error"] = str(e)[:50]
            if "STALE" not in str(STORE.ormuz.get("estado", "")):
                STORE.ormuz["estado"] = "⚪ STALE"

        await asyncio.sleep(intervalo)
