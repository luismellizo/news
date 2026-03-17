import asyncio
import requests
from datetime import datetime, timezone
import logging
from pydantic import BaseModel, Field

from backend.config import config
from backend.store import STORE
from backend.scrapers.correlations import correlate_with_volume

logger = logging.getLogger("Bloomberg")

class NewsSentiment(BaseModel):
    sentiment: str = Field(..., description="bullish, bearish, or neutral")
    confidence_score: float = Field(..., description="0.0 to 1.0 confidence")
    market_impact_justification: str = Field(..., description="Brief justification")

async def analyze_news_sentiment(headline: str, summary: str, source: str) -> NewsSentiment:
    """
    Placeholder para llamada a LLM (OpenAI/Anthropic/Gemini/FinBERT).
    Toma el headline y summary y fuerza una salida JSON estructurada con Pydantic.
    """
    try:
        # Aquí iría la integración con Instructor o client.beta.chat.completions.parse(response_model=NewsSentiment, ...)
        # Simularemos una lógica semántica mockeada para cumplir con la firma.
        texto = (headline + " " + summary).lower()
        if "surge" in texto or "beat" in texto or "upgrade" in texto or "record" in texto:
            return NewsSentiment(sentiment="bullish", confidence_score=0.85, market_impact_justification="Positive economic indicators detected via semantics.")
        elif "crash" in texto or "drop" in texto or "fear" in texto or "crisis" in texto:
            return NewsSentiment(sentiment="bearish", confidence_score=0.85, market_impact_justification="Negative market stress factors identified via semantics.")
        else:
            return NewsSentiment(sentiment="neutral", confidence_score=0.4, market_impact_justification="No clear directional market impact found.")
    except Exception as e:
        logger.error(f"Error en LLM Sentiment Analysis: {e}")
        return NewsSentiment(sentiment="neutral", confidence_score=0.0, market_impact_justification="Error in AI processing")

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
                STORE.macro["error"] = "Sin API key"
                await asyncio.sleep(intervalo)
                continue

            url = f"https://finnhub.io/api/v1/news?category=general&token={api_key}"
            loop = asyncio.get_event_loop()
            resp = await loop.run_in_executor(None, lambda: requests.get(url, timeout=10))

            if resp.status_code == 200:
                noticias = resp.json()[:10]
                total_score = 0.0
                processed_news = []
                
                for n in noticias:
                    headline = n.get("headline", "")
                    summary = n.get("summary", "")
                    source = n.get("source", "")
                    timestamp = n.get("datetime", 0)
                    
                    # Pasar por el LLM estructurado asincrónicamente
                    ai_analysis = await analyze_news_sentiment(headline, summary, source)
                    
                    # Ponderación dinámica de fuentes ("Source Weighting")
                    weight = source_weights.get(source, 1.0)
                    for k, v in source_weights.items():
                        if k.lower() in source.lower():
                            weight = v
                            break
                            
                    adjusted_confidence = min(ai_analysis.confidence_score * weight, 1.0)
                    
                    if ai_analysis.sentiment == "bullish":
                        total_score += adjusted_confidence
                    elif ai_analysis.sentiment == "bearish":
                        total_score -= adjusted_confidence
                    
                    # Validación de correlación de volumen para front-running (ALREADY_PRICED_IN)
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
            logger.error(f"Error fetching macro news: {e}")
            STORE.macro["error"] = str(e)[:50]

        await asyncio.sleep(intervalo)
