import asyncio
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import logging

from backend.config import config
from backend.store import STORE

logger = logging.getLogger("Bloomberg")

async def scraper_btc_etf_inflows():
    delay = config.get("scraper_delay_segundos", 2)
    intervalo = config.get("refresh_etf_inflows_minutos", 5) * 60

    while True:
        try:
            await asyncio.sleep(delay)
            headers = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"}

            loop = asyncio.get_event_loop()
            resp = await loop.run_in_executor(None, lambda: requests.get("https://farside.co.uk/btc/", headers=headers, timeout=15))

            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "lxml")
                tablas = soup.find_all("table")
                net_flow_hoy = 0.0
                detalles = []

                for tabla in tablas:
                    filas = tabla.find_all("tr")
                    for fila in filas:
                        celdas = fila.find_all(["td", "th"])
                        textos = [c.get_text(strip=True) for c in celdas]

                        if len(textos) >= 2:
                            for i, txt in enumerate(textos):
                                try:
                                    valor = float(txt.replace(",", "").replace("$", "").replace("(", "-").replace(")", "").strip())
                                    if abs(valor) > 0.01 and i > 0:
                                        detalles.append({"etf": textos[0] or f"Col{i}", "flow": valor})
                                except: pass

                    for fila in filas:
                        if "total" in fila.get_text(strip=True).lower():
                            for c in fila.find_all("td"):
                                try:
                                    val = float(c.get_text(strip=True).replace(",", "").replace("$", "").replace("(", "-").replace(")", ""))
                                    if abs(val) > 0.01: net_flow_hoy = val
                                except: pass

                STORE.btc_etf_inflows = {
                    "net_flow_hoy_millones": net_flow_hoy,
                    "acumulado_millones": 0.0,
                    "detalle": detalles[:10],
                    "ultima_actualizacion": datetime.now().strftime("%H:%M:%S"),
                    "error": ""
                }
            else:
                STORE.btc_etf_inflows["error"] = f"HTTP {resp.status_code}"
        except Exception as e:
            STORE.btc_etf_inflows["error"] = str(e)[:50]

        await asyncio.sleep(intervalo)
