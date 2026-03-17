#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════╗
║              MiBloombergEficaz_2026.py                              ║
║         Terminal de Trading Profesional — Estilo Bloomberg           ║
║                                                                      ║
║  Ventaja REAL: Datos fundamentales (ETF inflows, Ormuz, macro)       ║
║  antes que el 98% de traders retail.                                 ║
║                                                                      ║
║  Stack: Textual TUI + Finnhub WS + Scrapers + Telegram Alerts       ║
╚══════════════════════════════════════════════════════════════════════╝

INSTALACIÓN:
    pip install textual websockets requests beautifulsoup4 \
                python-telegram-bot aiohttp yfinance lxml

EJECUCIÓN:
    python MiBloombergEficaz_2026.py

Autor: MiBloombergEficaz | Fecha: 2026 | Licencia: MIT
"""

# =============================================================================
# IMPORTACIONES
# =============================================================================
import asyncio
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

import aiohttp
import requests
from bs4 import BeautifulSoup

# Textual TUI
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, Container
from textual.widgets import Header, Footer, Static, Label, RichLog
from textual.reactive import reactive
from textual.timer import Timer
from textual import work

# Telegram (async)
try:
    from telegram import Bot as TelegramBot
    TELEGRAM_DISPONIBLE = True
except ImportError:
    TELEGRAM_DISPONIBLE = False

# Fallback yfinance
try:
    import yfinance as yf
    YFINANCE_DISPONIBLE = True
except ImportError:
    YFINANCE_DISPONIBLE = False

# =============================================================================
# CONFIGURACIÓN — Carga/Genera config.json
# =============================================================================

RUTA_CONFIG = Path(__file__).parent / "config.json"
RUTA_LOG = Path(__file__).parent / "bloomberg_terminal.log"

CONFIG_DEFAULT = {
    "finnhub_api_key": "TU_API_KEY_FINNHUB_AQUI",
    "telegram_bot_token": "",
    "telegram_chat_id": "",
    "simbolos": {
        "spx_proxy": "SPY",
        "btc": "BINANCE:BTCUSDT",
        "oil_proxy": "USO"
    },
    "alertas": {
        "btc_etf_inflow_umbral_millones": 200,
        "ormuz_cambio_transitos_pct": 20,
        "niveles_precio": {
            "SPY": {"arriba": 665, "abajo": 600},
            "BINANCE:BTCUSDT": {"arriba": 120000, "abajo": 80000},
            "USO": {"arriba": 90, "abajo": 60}
        }
    },
    "scraper_delay_segundos": 2,
    "refresh_precios_segundos": 2,
    "refresh_etf_inflows_minutos": 5,
    "refresh_ormuz_minutos": 3,
    "refresh_macro_minutos": 10
}


def cargar_config() -> dict:
    """Carga config.json o genera uno por defecto si no existe."""
    if not RUTA_CONFIG.exists():
        with open(RUTA_CONFIG, "w", encoding="utf-8") as f:
            json.dump(CONFIG_DEFAULT, f, indent=4, ensure_ascii=False)
        print(f"⚙️  Config generado en: {RUTA_CONFIG}")
        print("   → Edita config.json con tu API key de Finnhub antes de ejecutar.")
        print("   → Obtén tu key gratis en: https://finnhub.io/")
    with open(RUTA_CONFIG, "r", encoding="utf-8") as f:
        return json.load(f)


# =============================================================================
# LOGGING — Archivo + consola
# =============================================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(RUTA_LOG, encoding="utf-8"),
    ]
)
logger = logging.getLogger("Bloomberg")


# =============================================================================
# STORE GLOBAL — Estado compartido entre componentes
# =============================================================================

class DataStore:
    """Almacén central de datos. Todos los componentes leen/escriben aquí."""

    def __init__(self):
        # Precios en tiempo real
        self.precios: dict[str, dict] = {
            "SPY": {"precio": 0.0, "cambio_pct": 0.0, "volumen": 0, "ts": ""},
            "BINANCE:BTCUSDT": {"precio": 0.0, "cambio_pct": 0.0, "volumen": 0, "ts": ""},
            "USO": {"precio": 0.0, "cambio_pct": 0.0, "volumen": 0, "ts": ""},
        }
        # Precios de cierre anterior (para calcular % cambio)
        self.precios_cierre: dict[str, float] = {}

        # ETF BTC Inflows
        self.btc_etf_inflows: dict = {
            "net_flow_hoy_millones": 0.0,
            "acumulado_millones": 0.0,
            "detalle": [],
            "ultima_actualizacion": "Sin datos",
            "error": ""
        }

        # Ormuz Strait
        self.ormuz: dict = {
            "estado": "DESCONOCIDO",
            "transitos_24h": 0,
            "tanqueros_esperando": 0,
            "trafico_caido_pct": 0.0,
            "ultima_actualizacion": "Sin datos",
            "error": "",
            "transitos_anterior": 0
        }

        # Macro / Noticias
        self.macro: dict = {
            "noticias": [],
            "sentiment_score": 0.0,
            "ultima_actualizacion": "Sin datos",
            "error": ""
        }

        # Estado de conexión
        self.ws_conectado: bool = False
        self.usando_fallback: bool = False

        # Historial de alertas (para cooldown)
        self.alertas_enviadas: dict[str, float] = {}

        # Sparklines de precios (últimos 30 ticks)
        self.historial_precios: dict[str, list[float]] = {
            "SPY": [],
            "BINANCE:BTCUSDT": [],
            "USO": [],
        }


STORE = DataStore()


# =============================================================================
# SPARKLINE — Mini gráfico de texto
# =============================================================================

SPARK_CHARS = "▁▂▃▄▅▆▇█"


def sparkline(datos: list[float], ancho: int = 20) -> str:
    """Genera sparkline de texto a partir de una lista de floats."""
    if not datos or len(datos) < 2:
        return "─" * ancho
    # Tomar los últimos 'ancho' puntos
    datos = datos[-ancho:]
    mn, mx = min(datos), max(datos)
    rango = mx - mn if mx != mn else 1
    indices = [int((v - mn) / rango * (len(SPARK_CHARS) - 1)) for v in datos]
    return "".join(SPARK_CHARS[i] for i in indices)


# =============================================================================
# FINNHUB WEBSOCKET — Precios en tiempo real
# =============================================================================

async def finnhub_websocket(config: dict):
    """
    Conexión WebSocket persistente a Finnhub.
    Suscribe a SPY, BTCUSDT, USO y actualiza el STORE.
    Reconnect automático con backoff exponencial.
    """
    import websockets

    api_key = config.get("finnhub_api_key", "")
    if not api_key or api_key == "TU_API_KEY_FINNHUB_AQUI":
        logger.warning("⚠️ No hay API key de Finnhub configurada. Usando fallback.")
        STORE.usando_fallback = True
        await _fallback_yfinance(config)
        return

    url = f"wss://ws.finnhub.io?token={api_key}"
    simbolos = [
        config["simbolos"]["spx_proxy"],
        config["simbolos"]["btc"],
        config["simbolos"]["oil_proxy"],
    ]

    intentos = 0
    max_intentos = 10

    while intentos < max_intentos:
        try:
            async with websockets.connect(url, ping_interval=30) as ws:
                STORE.ws_conectado = True
                STORE.usando_fallback = False
                intentos = 0  # Reset al conectar
                logger.info("✅ WebSocket Finnhub conectado")

                # Suscribir a símbolos
                for s in simbolos:
                    await ws.send(json.dumps({"type": "subscribe", "symbol": s}))
                    logger.info(f"📡 Suscrito a: {s}")

                # Loop de recepción
                async for mensaje in ws:
                    try:
                        data = json.loads(mensaje)
                        if data.get("type") == "trade" and data.get("data"):
                            for trade in data["data"]:
                                simbolo = trade.get("s", "")
                                precio = trade.get("p", 0.0)
                                volumen = trade.get("v", 0)
                                ts = trade.get("t", 0)

                                if simbolo in STORE.precios:
                                    # Calcular cambio %
                                    cierre = STORE.precios_cierre.get(simbolo, precio)
                                    cambio = ((precio - cierre) / cierre * 100) if cierre else 0

                                    STORE.precios[simbolo] = {
                                        "precio": precio,
                                        "cambio_pct": round(cambio, 2),
                                        "volumen": volumen,
                                        "ts": datetime.fromtimestamp(
                                            ts / 1000, tz=timezone.utc
                                        ).strftime("%H:%M:%S") if ts else ""
                                    }

                                    # Guardar en historial para sparkline
                                    hist = STORE.historial_precios.get(simbolo, [])
                                    hist.append(precio)
                                    if len(hist) > 60:
                                        hist = hist[-60:]
                                    STORE.historial_precios[simbolo] = hist

                    except (json.JSONDecodeError, KeyError) as e:
                        logger.debug(f"Mensaje WS ignorado: {e}")

        except Exception as e:
            STORE.ws_conectado = False
            intentos += 1
            espera = min(2 ** intentos, 60)
            logger.error(f"❌ WebSocket error (intento {intentos}): {e}. Retry en {espera}s")
            await asyncio.sleep(espera)

    # Si se agotaron los intentos, fallback
    logger.warning("⚠️ WebSocket agotó reintentos. Activando fallback yfinance.")
    STORE.usando_fallback = True
    await _fallback_yfinance(config)


async def _fallback_yfinance(config: dict):
    """Fallback: usar yfinance para obtener precios cada N segundos."""
    if not YFINANCE_DISPONIBLE:
        logger.error("❌ yfinance no está instalado. Sin datos de precios.")
        return

    simbolos_yf = {
        config["simbolos"]["spx_proxy"]: config["simbolos"]["spx_proxy"],
        "BTC-USD": config["simbolos"]["btc"],
        config["simbolos"]["oil_proxy"]: config["simbolos"]["oil_proxy"],
    }
    refresh = config.get("refresh_precios_segundos", 5)

    while True:
        try:
            for yf_sym, store_key in simbolos_yf.items():
                ticker = yf.Ticker(yf_sym)
                info = ticker.fast_info
                precio = getattr(info, "last_price", 0) or 0
                cierre = getattr(info, "previous_close", precio) or precio
                cambio = ((precio - cierre) / cierre * 100) if cierre else 0

                if store_key in STORE.precios:
                    STORE.precios[store_key] = {
                        "precio": round(precio, 2),
                        "cambio_pct": round(cambio, 2),
                        "volumen": 0,
                        "ts": datetime.now().strftime("%H:%M:%S")
                    }
                    STORE.precios_cierre[store_key] = cierre

                    hist = STORE.historial_precios.get(store_key, [])
                    hist.append(precio)
                    if len(hist) > 60:
                        hist = hist[-60:]
                    STORE.historial_precios[store_key] = hist

        except Exception as e:
            logger.error(f"❌ Fallback yfinance error: {e}")

        await asyncio.sleep(max(refresh, 3))


# =============================================================================
# OBTENER PRECIOS DE CIERRE (para calcular % cambio en WS)
# =============================================================================

def obtener_cierres(config: dict):
    """Obtiene precios de cierre del día anterior via Finnhub REST."""
    api_key = config.get("finnhub_api_key", "")
    if not api_key or api_key == "TU_API_KEY_FINNHUB_AQUI":
        return

    simbolos_rest = [
        config["simbolos"]["spx_proxy"],
        config["simbolos"]["oil_proxy"],
    ]

    for s in simbolos_rest:
        try:
            url = f"https://finnhub.io/api/v1/quote?symbol={s}&token={api_key}"
            resp = requests.get(url, timeout=10)
            data = resp.json()
            if "pc" in data and data["pc"]:
                STORE.precios_cierre[s] = data["pc"]
                STORE.precios[s]["precio"] = data.get("c", 0)
                STORE.precios[s]["cambio_pct"] = round(data.get("dp", 0), 2)
                logger.info(f"📊 Cierre {s}: ${data['pc']}")
        except Exception as e:
            logger.error(f"Error obteniendo cierre {s}: {e}")

    # BTC cierre via Finnhub crypto
    try:
        btc_sym = config["simbolos"]["btc"]
        url = f"https://finnhub.io/api/v1/quote?symbol={btc_sym}&token={api_key}"
        resp = requests.get(url, timeout=10)
        data = resp.json()
        if "pc" in data and data["pc"]:
            STORE.precios_cierre[btc_sym] = data["pc"]
            STORE.precios[btc_sym]["precio"] = data.get("c", 0)
            STORE.precios[btc_sym]["cambio_pct"] = round(data.get("dp", 0), 2)
    except Exception as e:
        logger.error(f"Error obteniendo cierre BTC: {e}")


# =============================================================================
# SCRAPER — BTC ETF INFLOWS (farside.co.uk)
# =============================================================================

async def scraper_btc_etf_inflows(config: dict):
    """
    Scraper de BTC ETF inflows desde farside.co.uk/btc
    Se ejecuta cada 5 minutos. Extrae net flow del día y acumulado.
    """
    delay = config.get("scraper_delay_segundos", 2)
    intervalo = config.get("refresh_etf_inflows_minutos", 5) * 60

    while True:
        try:
            await asyncio.sleep(delay)  # Anti-ban delay

            headers = {
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                              "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
            }

            # Hacer request en thread separado para no bloquear event loop
            loop = asyncio.get_event_loop()
            resp = await loop.run_in_executor(
                None,
                lambda: requests.get(
                    "https://farside.co.uk/btc/",
                    headers=headers,
                    timeout=15
                )
            )

            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "lxml")

                # Buscar tablas con datos de ETF
                tablas = soup.find_all("table")
                net_flow_hoy = 0.0
                acumulado = 0.0
                detalles = []

                for tabla in tablas:
                    filas = tabla.find_all("tr")
                    for fila in filas:
                        celdas = fila.find_all(["td", "th"])
                        textos = [c.get_text(strip=True) for c in celdas]

                        # Buscar filas con datos numéricos (flows en millones)
                        if len(textos) >= 2:
                            # Intentar parsear números de las celdas
                            for i, txt in enumerate(textos):
                                txt_limpio = txt.replace(",", "").replace("$", "").replace(
                                    "(", "-").replace(")", "").strip()
                                try:
                                    valor = float(txt_limpio)
                                    if abs(valor) > 0.01 and i > 0:
                                        # Posible dato de flow
                                        nombre_etf = textos[0] if textos[0] else f"Col{i}"
                                        detalles.append({
                                            "etf": nombre_etf,
                                            "flow": valor
                                        })
                                except (ValueError, IndexError):
                                    continue

                    # Buscar fila "Total" o última fila numérica
                    for fila in filas:
                        texto_fila = fila.get_text(strip=True).lower()
                        if "total" in texto_fila:
                            celdas = fila.find_all("td")
                            for c in celdas:
                                try:
                                    val = float(
                                        c.get_text(strip=True)
                                        .replace(",", "")
                                        .replace("$", "")
                                        .replace("(", "-")
                                        .replace(")", "")
                                    )
                                    if abs(val) > 0.01:
                                        net_flow_hoy = val
                                except (ValueError, AttributeError):
                                    continue

                STORE.btc_etf_inflows = {
                    "net_flow_hoy_millones": net_flow_hoy,
                    "acumulado_millones": acumulado,
                    "detalle": detalles[:10],  # Limitar a 10 ETFs
                    "ultima_actualizacion": datetime.now().strftime("%H:%M:%S"),
                    "error": ""
                }

                logger.info(
                    f"📊 ETF Inflows actualizado: Net={net_flow_hoy}M"
                )
            else:
                STORE.btc_etf_inflows["error"] = f"HTTP {resp.status_code}"
                logger.warning(f"⚠️ farside.co.uk respondió {resp.status_code}")

        except Exception as e:
            STORE.btc_etf_inflows["error"] = str(e)[:50]
            logger.error(f"❌ Error scraping ETF inflows: {e}")

        await asyncio.sleep(intervalo)


# =============================================================================
# SCRAPER — ORMUZ STRAIT MONITOR
# =============================================================================

async def scraper_ormuz(config: dict):
    """
    Scraper del Strait of Hormuz desde hormuzstraitmonitor.com
    Extrae: estado, tránsitos 24h, tanqueros esperando, % tráfico caído.
    Fallback graceful si el sitio no está disponible.
    """
    delay = config.get("scraper_delay_segundos", 2)
    intervalo = config.get("refresh_ormuz_minutos", 3) * 60

    while True:
        try:
            await asyncio.sleep(delay)

            headers = {
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                              "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
            }

            loop = asyncio.get_event_loop()
            resp = await loop.run_in_executor(
                None,
                lambda: requests.get(
                    "https://hormuzstraitmonitor.com/",
                    headers=headers,
                    timeout=15
                )
            )

            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "lxml")
                texto_completo = soup.get_text(separator=" ").lower()

                # Determinar estado
                if "restricted" in texto_completo or "closure" in texto_completo:
                    estado = "🔴 RESTRICTED"
                elif "normal" in texto_completo or "open" in texto_completo:
                    estado = "🟢 NORMAL"
                else:
                    estado = "🟡 MONITOREANDO"

                # Buscar números relevantes
                import re
                transitos = 0
                tanqueros = 0
                trafico_pct = 0.0

                # Buscar patrones como "XX transits" o "XX vessels"
                match_transitos = re.search(r'(\d+)\s*(?:transit|passage|ship)', texto_completo)
                if match_transitos:
                    transitos = int(match_transitos.group(1))

                match_tanqueros = re.search(r'(\d+)\s*(?:tanker|waiting|queue)', texto_completo)
                if match_tanqueros:
                    tanqueros = int(match_tanqueros.group(1))

                match_pct = re.search(r'(\d+\.?\d*)\s*%', texto_completo)
                if match_pct:
                    trafico_pct = float(match_pct.group(1))

                # Verificar cambio drástico en tránsitos
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

                logger.info(
                    f"🚢 Ormuz: {estado} | Tránsitos={transitos} | Tanqueros={tanqueros}"
                )
            else:
                STORE.ormuz["error"] = f"HTTP {resp.status_code}"

        except requests.exceptions.ConnectionError:
            STORE.ormuz["error"] = "Sitio no disponible"
            STORE.ormuz["estado"] = "⚪ SIN DATOS"
            logger.warning("⚠️ hormuzstraitmonitor.com no disponible — fallback activo")
        except Exception as e:
            STORE.ormuz["error"] = str(e)[:50]
            logger.error(f"❌ Error scraping Ormuz: {e}")

        await asyncio.sleep(intervalo)


# =============================================================================
# MACRO / NOTICIAS — Finnhub News API
# =============================================================================

async def fetch_macro_noticias(config: dict):
    """
    Obtiene noticias macro y calcula un sentiment score básico
    usando la API REST de Finnhub (news endpoint).
    """
    api_key = config.get("finnhub_api_key", "")
    intervalo = config.get("refresh_macro_minutos", 10) * 60

    # Palabras para sentiment básico
    POSITIVAS = {
        "surge", "rally", "gain", "bull", "growth", "record", "high",
        "optimism", "recovery", "beat", "strong", "upgrade", "sube",
        "alza", "máximo", "recupera"
    }
    NEGATIVAS = {
        "crash", "plunge", "drop", "bear", "recession", "fear", "low",
        "sell", "warning", "crisis", "downgrade", "war", "baja",
        "caída", "mínimo", "pérdida"
    }

    while True:
        try:
            if not api_key or api_key == "TU_API_KEY_FINNHUB_AQUI":
                STORE.macro["error"] = "Sin API key"
                await asyncio.sleep(intervalo)
                continue

            url = f"https://finnhub.io/api/v1/news?category=general&token={api_key}"
            loop = asyncio.get_event_loop()
            resp = await loop.run_in_executor(
                None, lambda: requests.get(url, timeout=10)
            )

            if resp.status_code == 200:
                noticias = resp.json()[:15]  # Top 15

                # Calcular sentiment
                score = 0
                for n in noticias:
                    titulo = (n.get("headline", "") + " " + n.get("summary", "")).lower()
                    for p in POSITIVAS:
                        if p in titulo:
                            score += 1
                    for neg in NEGATIVAS:
                        if neg in titulo:
                            score -= 1

                # Normalizar score a -100..+100
                max_score = max(len(noticias), 1)
                score_normalizado = round((score / max_score) * 100, 1)

                STORE.macro = {
                    "noticias": [
                        {
                            "headline": n.get("headline", "")[:80],
                            "source": n.get("source", ""),
                            "time": datetime.fromtimestamp(
                                n.get("datetime", 0), tz=timezone.utc
                            ).strftime("%H:%M") if n.get("datetime") else ""
                        }
                        for n in noticias[:8]
                    ],
                    "sentiment_score": score_normalizado,
                    "ultima_actualizacion": datetime.now().strftime("%H:%M:%S"),
                    "error": ""
                }

                logger.info(f"📰 Noticias actualizadas. Sentiment: {score_normalizado}")
            else:
                STORE.macro["error"] = f"HTTP {resp.status_code}"

        except Exception as e:
            STORE.macro["error"] = str(e)[:50]
            logger.error(f"❌ Error noticias: {e}")

        await asyncio.sleep(intervalo)


# =============================================================================
# TELEGRAM ALERTER — Sistema de alertas
# =============================================================================

class AlertaTelegram:
    """
    Sistema de alertas via Telegram.
    Cooldown de 5 minutos entre alertas del mismo tipo (anti-spam).
    """

    def __init__(self, config: dict):
        self.token = config.get("telegram_bot_token", "")
        self.chat_id = config.get("telegram_chat_id", "")
        self.config_alertas = config.get("alertas", {})
        self.cooldown = 300  # 5 minutos
        self.activo = bool(self.token and self.chat_id and TELEGRAM_DISPONIBLE)

        if self.activo:
            self.bot = TelegramBot(token=self.token)
            logger.info("✅ Telegram alertas activas")
        else:
            self.bot = None
            logger.info("ℹ️ Telegram alertas desactivadas (sin token/chat_id)")

    async def enviar(self, tipo: str, mensaje: str):
        """Envía alerta si no está en cooldown."""
        if not self.activo:
            return

        ahora = time.time()
        ultima = STORE.alertas_enviadas.get(tipo, 0)
        if ahora - ultima < self.cooldown:
            return  # En cooldown

        try:
            texto = f"🚨 *BLOOMBERG ALERT*\n\n{mensaje}"
            await self.bot.send_message(
                chat_id=self.chat_id,
                text=texto,
                parse_mode="Markdown"
            )
            STORE.alertas_enviadas[tipo] = ahora
            logger.info(f"📨 Alerta enviada [{tipo}]: {mensaje[:50]}")

            # Beep en terminal
            print("\a", end="", flush=True)

        except Exception as e:
            logger.error(f"❌ Error enviando alerta Telegram: {e}")

    async def verificar_alertas(self):
        """Verifica todas las condiciones de alerta."""
        alertas_cfg = self.config_alertas

        # 1. BTC ETF Inflow > umbral
        umbral_etf = alertas_cfg.get("btc_etf_inflow_umbral_millones", 200)
        flow = STORE.btc_etf_inflows.get("net_flow_hoy_millones", 0)
        if abs(flow) > umbral_etf:
            signo = "+" if flow > 0 else ""
            await self.enviar(
                "etf_inflow",
                f"📊 BTC ETF Net Flow: {signo}{flow}M USD\n"
                f"Acumulado: {STORE.btc_etf_inflows.get('acumulado_millones', 0)}M"
            )

        # 2. Ormuz tránsitos cambio drástico
        pct_umbral = alertas_cfg.get("ormuz_cambio_transitos_pct", 20)
        transitos = STORE.ormuz.get("transitos_24h", 0)
        anterior = STORE.ormuz.get("transitos_anterior", 0)
        if anterior and transitos:
            cambio_pct = abs((transitos - anterior) / anterior * 100)
            if cambio_pct > pct_umbral:
                await self.enviar(
                    "ormuz",
                    f"🚢 Ormuz: Tránsitos cambiaron {cambio_pct:.0f}%\n"
                    f"Anterior: {anterior} → Actual: {transitos}\n"
                    f"Estado: {STORE.ormuz.get('estado', '?')}"
                )

        # 3. Precio cruza niveles
        niveles = alertas_cfg.get("niveles_precio", {})
        for simbolo, limits in niveles.items():
            precio = STORE.precios.get(simbolo, {}).get("precio", 0)
            if precio <= 0:
                continue
            if precio >= limits.get("arriba", float("inf")):
                await self.enviar(
                    f"precio_arriba_{simbolo}",
                    f"📈 {simbolo}: ${precio:,.2f} cruzó nivel superior ${limits['arriba']:,.2f}"
                )
            if precio <= limits.get("abajo", 0):
                await self.enviar(
                    f"precio_abajo_{simbolo}",
                    f"📉 {simbolo}: ${precio:,.2f} cruzó nivel inferior ${limits['abajo']:,.2f}"
                )


# =============================================================================
# WIDGETS TEXTUAL — Paneles individuales
# =============================================================================

class PanelPrecio(Static):
    """Panel de precio con sparkline, cambio % y datos clave."""

    def __init__(
        self, titulo: str, simbolo: str, emoji: str = "📊",
        extra_fn=None, **kwargs
    ):
        super().__init__(**kwargs)
        self.titulo = titulo
        self.simbolo = simbolo
        self.emoji = emoji
        self.extra_fn = extra_fn  # Función que retorna info extra

    def render_panel(self) -> str:
        datos = STORE.precios.get(self.simbolo, {})
        precio = datos.get("precio", 0)
        cambio = datos.get("cambio_pct", 0)
        ts = datos.get("ts", "")
        hist = STORE.historial_precios.get(self.simbolo, [])

        # Color del cambio
        if cambio > 0:
            color_cambio = "[bold green]"
            flecha = "▲"
        elif cambio < 0:
            color_cambio = "[bold red]"
            flecha = "▼"
        else:
            color_cambio = "[bold yellow]"
            flecha = "─"

        # Formato del precio
        if precio > 1000:
            precio_fmt = f"${precio:,.2f}"
        elif precio > 0:
            precio_fmt = f"${precio:.4f}"
        else:
            precio_fmt = "$---"

        spark = sparkline(hist)

        # Línea extra (ETF inflows para BTC, Ormuz para OIL)
        extra = ""
        if self.extra_fn:
            extra = self.extra_fn()

        return (
            f"[bold cyan]{self.emoji} {self.titulo}[/]\n"
            f"{'─' * 36}\n"
            f"[bold white]{precio_fmt}[/]  "
            f"{color_cambio}{flecha} {cambio:+.2f}%[/]\n"
            f"[dim]{spark}[/]\n"
            f"[dim]Últ: {ts or '---'}[/]\n"
            f"{extra}"
        )


class PanelMacro(Static):
    """Panel de noticias macro y sentiment."""

    def render_panel(self) -> str:
        macro = STORE.macro
        sentiment = macro.get("sentiment_score", 0)
        noticias = macro.get("noticias", [])
        error = macro.get("error", "")
        ts = macro.get("ultima_actualizacion", "---")

        # Barra de sentiment
        if sentiment > 20:
            sent_color = "[bold green]"
            sent_emoji = "🟢 BULLISH"
        elif sentiment < -20:
            sent_color = "[bold red]"
            sent_emoji = "🔴 BEARISH"
        else:
            sent_color = "[bold yellow]"
            sent_emoji = "🟡 NEUTRAL"

        lineas = [
            f"[bold cyan]📰 MACRO & NEWS[/]",
            f"{'─' * 36}",
            f"Sentiment: {sent_color}{sent_emoji} ({sentiment:+.1f})[/]",
            "",
        ]

        if error:
            lineas.append(f"[bold red]⚠ {error}[/]")
        else:
            for n in noticias[:5]:
                headline = n.get("headline", "")[:45]
                source = n.get("source", "")[:8]
                hora = n.get("time", "")
                lineas.append(f"[dim]{hora}[/] {headline}")
                lineas.append(f"       [dim italic]{source}[/]")

        lineas.append(f"\n[dim]Actualizado: {ts}[/]")
        return "\n".join(lineas)


# =============================================================================
# APP TEXTUAL — Interfaz principal
# =============================================================================

# CSS embebido — estilo Bloomberg oscuro
APP_CSS = """
Screen {
    layout: grid;
    grid-size: 2 2;
    grid-gutter: 1;
    background: #0a0a0a;
    padding: 1;
}

.panel {
    background: #111111;
    border: solid #333333;
    padding: 1 2;
    height: 100%;
    min-height: 12;
}

.panel:focus {
    border: solid #ff6600;
}

#panel-spx {
    border: solid #1a5276;
}

#panel-btc {
    border: solid #7d3c98;
}

#panel-oil {
    border: solid #1e8449;
}

#panel-macro {
    border: solid #b9770e;
}

Header {
    background: #ff6600;
    color: #000000;
    text-style: bold;
}

Footer {
    background: #1a1a1a;
}

Static {
    color: #cccccc;
}
"""


class BloombergApp(App):
    """Aplicación principal — Terminal Bloomberg Eficaz 2026."""

    CSS = APP_CSS
    TITLE = "MiBloomberg Eficaz 2026"
    SUB_TITLE = "Terminal de Trading Profesional"

    BINDINGS = [
        ("q", "quit", "Salir"),
        ("r", "refresh", "Refresh"),
        ("a", "alertas", "Alertas"),
    ]

    def __init__(self, config: dict):
        super().__init__()
        self.config = config
        self.alerter = AlertaTelegram(config)

    def compose(self) -> ComposeResult:
        yield Header()

        # Panel 1: SPX / SPY
        self.panel_spx = PanelPrecio(
            titulo="US500 / SPY",
            simbolo=self.config["simbolos"]["spx_proxy"],
            emoji="🇺🇸",
            id="panel-spx",
            classes="panel"
        )
        yield self.panel_spx

        # Panel 2: BTC con ETF inflows
        self.panel_btc = PanelPrecio(
            titulo="BTC / USDT",
            simbolo=self.config["simbolos"]["btc"],
            emoji="₿",
            extra_fn=self._info_btc_etf,
            id="panel-btc",
            classes="panel"
        )
        yield self.panel_btc

        # Panel 3: OIL con Ormuz
        self.panel_oil = PanelPrecio(
            titulo="WTI / USO",
            simbolo=self.config["simbolos"]["oil_proxy"],
            emoji="🛢️",
            extra_fn=self._info_ormuz,
            id="panel-oil",
            classes="panel"
        )
        yield self.panel_oil

        # Panel 4: Macro
        self.panel_macro = PanelMacro(
            id="panel-macro",
            classes="panel"
        )
        yield self.panel_macro

        yield Footer()

    def on_mount(self) -> None:
        """Inicia timers y tareas async al montar la app."""
        # Obtener precios de cierre iniciales
        try:
            obtener_cierres(self.config)
        except Exception as e:
            logger.error(f"Error obteniendo cierres: {e}")

        # Timer para refrescar UI
        refresh = self.config.get("refresh_precios_segundos", 2)
        self.set_interval(refresh, self._actualizar_paneles)

        # Timer para verificar alertas (cada 30s)
        self.set_interval(30, self._verificar_alertas)

        # Lanzar tareas async en background
        self._iniciar_background_tasks()

    @work(thread=True)
    def _iniciar_background_tasks(self):
        """Inicia todas las tareas de background en un event loop propio."""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        tareas = [
            finnhub_websocket(self.config),
            scraper_btc_etf_inflows(self.config),
            scraper_ormuz(self.config),
            fetch_macro_noticias(self.config),
        ]

        loop.run_until_complete(asyncio.gather(*tareas, return_exceptions=True))

    def _actualizar_paneles(self) -> None:
        """Refresca todos los paneles con datos actuales del STORE."""
        # Actualizar status de conexión en header
        if STORE.ws_conectado:
            self.sub_title = "🟢 EN VIVO — Finnhub WebSocket"
        elif STORE.usando_fallback:
            self.sub_title = "🟡 FALLBACK — yfinance"
        else:
            self.sub_title = "🔴 SIN CONEXIÓN"

        # Refrescar cada panel
        self.panel_spx.update(self.panel_spx.render_panel())
        self.panel_btc.update(self.panel_btc.render_panel())
        self.panel_oil.update(self.panel_oil.render_panel())
        self.panel_macro.update(self.panel_macro.render_panel())

    async def _verificar_alertas(self) -> None:
        """Ejecuta verificación periódica de condiciones de alerta."""
        try:
            await self.alerter.verificar_alertas()
        except Exception as e:
            logger.error(f"Error verificando alertas: {e}")

    # ─── Funciones de info extra para paneles ─────────────────────────

    def _info_btc_etf(self) -> str:
        """Info adicional de ETF inflows para el panel BTC."""
        etf = STORE.btc_etf_inflows
        flow = etf.get("net_flow_hoy_millones", 0)
        error = etf.get("error", "")
        ts = etf.get("ultima_actualizacion", "---")

        if error:
            return f"\n[bold yellow]ETF: ⚠ {error}[/]"

        if flow > 0:
            color = "[bold green]"
        elif flow < 0:
            color = "[bold red]"
        else:
            color = "[dim]"

        return (
            f"\n[bold]── ETF INFLOWS ──[/]\n"
            f"Net hoy: {color}${flow:+,.0f}M[/]\n"
            f"[dim]Actualizado: {ts}[/]"
        )

    def _info_ormuz(self) -> str:
        """Info adicional de Ormuz para el panel OIL."""
        o = STORE.ormuz
        estado = o.get("estado", "⚪ SIN DATOS")
        transitos = o.get("transitos_24h", 0)
        tanqueros = o.get("tanqueros_esperando", 0)
        error = o.get("error", "")
        ts = o.get("ultima_actualizacion", "---")

        if error:
            return f"\n[bold yellow]Ormuz: ⚠ {error}[/]"

        return (
            f"\n[bold]── ORMUZ STRAIT ──[/]\n"
            f"Estado: {estado}\n"
            f"Tránsitos 24h: [white]{transitos}[/]\n"
            f"Tanqueros: [white]{tanqueros}[/]\n"
            f"[dim]Actualizado: {ts}[/]"
        )

    # ─── Acciones de teclado ──────────────────────────────────────────

    def action_refresh(self) -> None:
        """Forzar refresh manual."""
        self._actualizar_paneles()
        self.notify("🔄 Datos refrescados", timeout=2)

    def action_alertas(self) -> None:
        """Mostrar info de alertas."""
        n = len(STORE.alertas_enviadas)
        tg = "✅ Activo" if self.alerter.activo else "❌ Inactivo"
        self.notify(
            f"Telegram: {tg} | Alertas enviadas: {n}",
            timeout=5
        )


# =============================================================================
# MAIN — Punto de entrada
# =============================================================================

def main():
    """Punto de entrada principal."""
    print("""
╔══════════════════════════════════════════════════════════════╗
║           MiBloombergEficaz_2026                             ║
║     Terminal de Trading Profesional — v1.0                    ║
╚══════════════════════════════════════════════════════════════╝
    """)

    # Cargar configuración
    config = cargar_config()

    # Verificar API key
    if config.get("finnhub_api_key") == "TU_API_KEY_FINNHUB_AQUI":
        print("⚠️  IMPORTANTE: Edita config.json con tu API key de Finnhub.")
        print("   → Regístrate gratis en: https://finnhub.io/")
        print("   → Copia tu API key y pégala en config.json")
        print("   → El terminal arrancará en modo fallback (yfinance)\n")

    # Lanzar app Textual
    app = BloombergApp(config=config)
    app.run()


if __name__ == "__main__":
    main()


# =============================================================================
# ═══════════════════════════════════════════════════════════════════════════════
#                     📖 GUÍA DE USO Y CONFIGURACIÓN
# ═══════════════════════════════════════════════════════════════════════════════
#
# ┌─────────────────────────────────────────────────────────────────────┐
# │                    CÓMO USARLO EN 5 MINUTOS                        │
# └─────────────────────────────────────────────────────────────────────┘
#
# 1. INSTALAR DEPENDENCIAS:
#    pip install textual websockets requests beautifulsoup4 \
#                python-telegram-bot aiohttp yfinance lxml
#
# 2. OBTENER API KEY DE FINNHUB (gratis, 10 segundos):
#    → Ve a https://finnhub.io/
#    → Regístrate con email
#    → Copia tu API key del dashboard
#
# 3. CONFIGURAR:
#    → Ejecuta una vez: python MiBloombergEficaz_2026.py
#    → Se genera config.json automáticamente
#    → Edita config.json: pon tu finnhub_api_key
#
# 4. (OPCIONAL) CONFIGURAR TELEGRAM:
#    → Busca @BotFather en Telegram
#    → Envía /newbot y sigue las instrucciones
#    → Copia el token del bot → config.json → telegram_bot_token
#    → Envía un mensaje a tu bot, luego ve a:
#      https://api.telegram.org/bot<TOKEN>/getUpdates
#    → Busca "chat":{"id":XXXXX} → config.json → telegram_chat_id
#
# 5. EJECUTAR:
#    python MiBloombergEficaz_2026.py
#
# ┌─────────────────────────────────────────────────────────────────────┐
# │           CONTROLES EN EL TERMINAL                                  │
# └─────────────────────────────────────────────────────────────────────┘
#
#   q  → Salir
#   r  → Forzar refresh de todos los paneles
#   a  → Ver estado de alertas Telegram
#
# ┌─────────────────────────────────────────────────────────────────────┐
# │            CÓMO AÑADIR MÁS ACTIVOS                                 │
# └─────────────────────────────────────────────────────────────────────┘
#
# 1. AÑADIR NUEVO SÍMBOLO AL WEBSOCKET:
#    → En config.json, añade el símbolo en la sección "simbolos"
#    → En el código, añade una entrada en STORE.precios con el símbolo
#    → Añade un PanelPrecio en el método compose() de BloombergApp
#    → Ajusta el CSS grid-size si necesitas más paneles (ej: 3 2)
#
# 2. SÍMBOLOS DISPONIBLES EN FINNHUB FREE TIER:
#    → US Stocks: AAPL, TSLA, NVDA, MSFT, AMZN, GOOGL, META...
#    → Crypto: BINANCE:ETHUSDT, BINANCE:SOLUSDT, BINANCE:XRPUSDT...
#    → ETFs: QQQ (Nasdaq), GLD (Oro), TLT (Bonos)...
#
# 3. EJEMPLO — AÑADIR ETHEREUM:
#    a) config.json:
#       "simbolos": { ..., "eth": "BINANCE:ETHUSDT" }
#    b) Código STORE.__init__:
#       "BINANCE:ETHUSDT": {"precio": 0, "cambio_pct": 0, ...}
#    c) Código BloombergApp.compose():
#       self.panel_eth = PanelPrecio(
#           titulo="ETH/USDT", simbolo="BINANCE:ETHUSDT",
#           emoji="⟠", id="panel-eth", classes="panel"
#       )
#       yield self.panel_eth
#    d) CSS: grid-size: 3 2;  (o 2 3 para 6 paneles)
#
# 4. AÑADIR NUEVO SCRAPER:
#    → Crea una función async: async def mi_scraper(config):
#    → Usa requests + BeautifulSoup para el parsing
#    → Guarda datos en STORE (crea nuevos campos)
#    → Añade la función a _iniciar_background_tasks()
#    → Crea un widget para mostrar los datos
#
# ┌─────────────────────────────────────────────────────────────────────┐
# │         NOTAS TÉCNICAS                                              │
# └─────────────────────────────────────────────────────────────────────┘
#
# • El WebSocket de Finnhub free tier tiene límite de 30 msg/segundo
# • Los scrapers usan delay anti-ban configurable (default: 2s)
# • El fallback a yfinance se activa automáticamente si WS falla
# • Los logs se guardan en bloomberg_terminal.log
# • Las alertas de Telegram tienen cooldown de 5 min (anti-spam)
# • Si el terminal se cierra inesperadamente, revisa el log
#
# =============================================================================
