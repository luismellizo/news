import asyncio
import requests
from datetime import datetime, timezone
import logging

from backend.config import config
from backend.store import STORE

logger = logging.getLogger("Bloomberg")

async def fetch_macro_noticias():
    api_key = config.get("finnhub_api_key", "")
    intervalo = config.get("refresh_macro_minutos", 10) * 60

    POSITIVAS = {"surge", "rally", "gain", "bull", "growth", "record", "high", "optimism", "recovery", "beat", "strong", "upgrade", "sube", "alza", "máximo", "recupera"}
    NEGATIVAS = {"crash", "plunge", "drop", "bear", "recession", "fear", "low", "sell", "warning", "crisis", "downgrade", "war", "baja", "caída", "mínimo", "pérdida"}

    while True:
        try:
            if not api_key or api_key == "TU_API_KEY_FINNHUB_AQUI":
                STORE.macro["error"] = "Sin API key"
                await asyncio.sleep(intervalo)
                continue

            url = f"https://finnhub.io/api/v1/news?category=general&token={api_key}"
            loop = asyncio.get_event_loop()
            resp = await loop.run_in_executor(None, lambda: requests.get(url, timeout=10))

            if resp.status_code == 200:
                noticias = resp.json()[:15]
                score = 0
                for n in noticias:
                    titulo = (n.get("headline", "") + " " + n.get("summary", "")).lower()
                    for p in POSITIVAS:
                        if p in titulo: score += 1
                    for neg in NEGATIVAS:
                        if neg in titulo: score -= 1

                max_score = max(len(noticias), 1)
                score_normalizado = round((score / max_score) * 100, 1)

                STORE.macro = {
                    "noticias": [
                        {
                            "headline": n.get("headline", "")[:80],
                            "source": n.get("source", ""),
                            "time": datetime.fromtimestamp(n.get("datetime", 0), tz=timezone.utc).strftime("%H:%M") if n.get("datetime") else ""
                        } for n in noticias[:8]
                    ],
                    "sentiment_score": score_normalizado,
                    "ultima_actualizacion": datetime.now().strftime("%H:%M:%S"),
                    "error": ""
                }
            else:
                STORE.macro["error"] = f"HTTP {resp.status_code}"

        except Exception as e:
            STORE.macro["error"] = str(e)[:50]

        await asyncio.sleep(intervalo)
