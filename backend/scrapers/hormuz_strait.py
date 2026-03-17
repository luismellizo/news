import asyncio
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import re
import logging

from backend.config import config
from backend.store import STORE

logger = logging.getLogger("Bloomberg")

async def scraper_ormuz():
    delay = config.get("scraper_delay_segundos", 2)
    intervalo = config.get("refresh_ormuz_minutos", 3) * 60

    while True:
        try:
            await asyncio.sleep(delay)
            headers = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"}

            loop = asyncio.get_event_loop()
            resp = await loop.run_in_executor(None, lambda: requests.get("https://hormuzstraitmonitor.com/", headers=headers, timeout=15))

            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "lxml")
                texto_completo = soup.get_text(separator=" ").lower()

                estado = "🟡 MONITOREANDO"
                if "restricted" in texto_completo or "closure" in texto_completo: estado = "🔴 RESTRICTED"
                elif "normal" in texto_completo or "open" in texto_completo: estado = "🟢 NORMAL"

                transitos, tanqueros, trafico_pct = 0, 0, 0.0
                match_transitos = re.search(r'(\d+)\s*(?:transit|passage|ship)', texto_completo)
                if match_transitos: transitos = int(match_transitos.group(1))

                match_tanqueros = re.search(r'(\d+)\s*(?:tanker|waiting|queue)', texto_completo)
                if match_tanqueros: tanqueros = int(match_tanqueros.group(1))

                match_pct = re.search(r'(\d+\.?\d*)\s*%', texto_completo)
                if match_pct: trafico_pct = float(match_pct.group(1))

                anterior = STORE.ormuz.get("transitos_anterior", 0)

                STORE.ormuz = {
                    "estado": estado,
                    "transitos_24h": transitos,
                    "tanqueros_esperando": tanqueros,
                    "trafico_caido_pct": trafico_pct,
                    "ultima_actualizacion": datetime.now().strftime("%H:%M:%S"),
                    "error": "",
                    "transitos_anterior": anterior if anterior else transitos
                }
            else:
                STORE.ormuz["error"] = f"HTTP {resp.status_code}"

        except requests.exceptions.ConnectionError:
            STORE.ormuz["error"] = "Sitio no disponible"
            STORE.ormuz["estado"] = "⚪ SIN DATOS"
        except Exception as e:
            STORE.ormuz["error"] = str(e)[:50]

        await asyncio.sleep(intervalo)
