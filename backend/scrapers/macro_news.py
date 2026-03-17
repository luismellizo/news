import asyncio
import requests
from datetime import datetime, timezone
import logging
from pydantic import BaseModel, Field
import instructor
from openai import AsyncOpenAI

from backend.config import config
from backend.store import STORE
from backend.scrapers.correlations import correlate_with_volume

logger = logging.getLogger("Bloomberg")

# Definición del esquema estructurado para la IA
class NewsSentiment(BaseModel):
    sentiment: str = Field(..., description="Must be 'bullish', 'bearish', or 'neutral'")
    confidence_score: float = Field(..., description="A confidence score from 0.0 to 1.0 reflecting how clear the directional market impact is.")
    market_impact_justification: str = Field(..., description="Brief justification of why the market could react this way based solely on the text.")

# Inicialización del cliente OpenAI parcheado con Instructor para validación Pydantic
# Requiere OPENAI_API_KEY en el entorno
client = instructor.from_openai(AsyncOpenAI())

async def analyze_news_sentiment(headline: str, summary: str, source: str) -> NewsSentiment:
    """
    Llamada REAL asíncrona a GPT-4o-mini usando Instructor para análisis semántico.
    CERO lógica de palabras clave. Extrae sentimiento puro del contexto.
    """
    try:
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            response_model=NewsSentiment,
            messages=[
                {
                    "role": "system",
                    "content": "You are a professional market analyst. Analyze the following news and determine its impact on the US markets."
                },
                {
                    "role": "user", 
                    "content": f"Source: {source}\nHeadline: {headline}\nSummary: {summary}"
                }
            ],
            temperature=0,
        )
        return response
    except Exception as e:
        logger.error(f"Error analizando sentimiento con LLM: {e}")
        # Valor seguro en caso de fallo de API pero manteniendo la estructura
        return NewsSentiment(
            sentiment="neutral", 
            confidence_score=0.0, 
            market_impact_justification=f"API Error: {str(e)}"
        )

async def fetch_macro_noticias():
    api_key = config.get("finnhub_api_key", "")
    intervalo = config.get("refresh_macro_minutos", 10) * 60

    source_weights = {
        "Federal Reserve": 1.5,
        "Bloomberg": 1.2,
        "Reuters": 1.1,
        "Yahoo": 0.8
    }

    while True:
        try:
            if not api_key or api_key == "TU_API_KEY_FINNHUB_AQUI":
                STORE.macro["error"] = "Sin API key de Finnhub"
                await asyncio.sleep(intervalo)
                continue

            url = f"https://finnhub.io/api/v1/news?category=general&token={api_key}"
            loop = asyncio.get_event_loop()
            resp = await loop.run_in_executor(None, lambda: requests.get(url, timeout=10))

            if resp.status_code == 200:
                noticias = resp.json()[:10]
                total_score = 0.0
                processed_news = []
                
                # Ejecutamos análisis en paralelo para reducir latencia total del batch
                tareas_sentiment = [
                    analyze_news_sentiment(n.get("headline", ""), n.get("summary", ""), n.get("source", ""))
                    for n in noticias
                ]
                sentimientos = await asyncio.gather(*tareas_sentiment)

                for idx, n in enumerate(noticias):
                    headline = n.get("headline", "")
                    source = n.get("source", "")
                    timestamp = n.get("datetime", 0)
                    ai_analysis = sentimientos[idx]
                    
                    # Ponderación de fuente
                    weight = 1.0
                    for k, v in source_weights.items():
                        if k.lower() in source.lower():
                            weight = v
                            break
                            
                    adjusted_confidence = min(ai_analysis.confidence_score * weight, 1.0)
                    
                    if ai_analysis.sentiment == "bullish":
                        total_score += adjusted_confidence
                    elif ai_analysis.sentiment == "bearish":
                        total_score -= adjusted_confidence
                    
                    # Verificación de si el mercado ya reaccionó (front-running)
                    latency_ts = datetime.now(timezone.utc).timestamp()
                    priced_in = await correlate_with_volume("SPY", timestamp)

                    processed_news.append({
                        "headline": headline[:80],
                        "source": source,
                        "time": datetime.fromtimestamp(timestamp, tz=timezone.utc).strftime("%H:%M") if timestamp else "",
                        "latency_timestamp": latency_ts,
                        "sentiment": ai_analysis.sentiment,
                        "priced_in": priced_in,
                        "justification": ai_analysis.market_impact_justification
                    })

                max_score = max(len(noticias), 1)
                score_normalizado = round((total_score / max_score) * 100, 1)

                STORE.macro = {
                    "noticias": processed_news,
                    "sentiment_score": score_normalizado,
                    "ultima_actualizacion": datetime.now().strftime("%H:%M:%S"),
                    "error": ""
                }
            else:
                STORE.macro["error"] = f"HTTP {resp.status_code}"

        except Exception as e:
            logger.error(f"Error procesando noticias con AI: {e}")
            STORE.macro["error"] = str(e)[:50]

        await asyncio.sleep(intervalo)
