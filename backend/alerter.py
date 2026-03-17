import asyncio
import time
import logging

from backend.config import config
from backend.store import STORE

logger = logging.getLogger("Bloomberg")

TELEGRAM_DISPONIBLE = True
try:
    from telegram import Bot as TelegramBot
except ImportError:
    TELEGRAM_DISPONIBLE = False

class AlertaTelegram:
    def __init__(self):
        self.token = config.get("telegram_bot_token", "")
        self.chat_id = config.get("telegram_chat_id", "")
        self.config_alertas = config.get("alertas", {})
        self.cooldown = 300
        self.activo = bool(self.token and self.chat_id and TELEGRAM_DISPONIBLE)

        if self.activo:
            self.bot = TelegramBot(token=self.token)
        else:
            self.bot = None

    async def enviar(self, tipo: str, mensaje: str):
        if not self.activo: return

        ahora = time.time()
        ultima = STORE.alertas_enviadas.get(tipo, 0)
        if ahora - ultima < self.cooldown: return

        try:
            texto = f"🚨 *BLOOMBERG ALERT*\n\n{mensaje}"
            await self.bot.send_message(chat_id=self.chat_id, text=texto, parse_mode="Markdown")
            STORE.alertas_enviadas[tipo] = ahora
            logger.info(f"📨 Alerta enviada [{tipo}]")
            print("\a", end="", flush=True)
        except Exception as e:
            logger.error(f"Error enviando alerta Telegram: {e}")

    async def verificar_alertas(self):
        alertas_cfg = self.config_alertas

        umbral_etf = alertas_cfg.get("btc_etf_inflow_umbral_millones", 200)
        flow = STORE.btc_etf_inflows.get("net_flow_hoy_millones", 0)
        if abs(flow) > umbral_etf:
            signo = "+" if flow > 0 else ""
            await self.enviar("etf_inflow", f"📊 BTC ETF Net Flow: {signo}{flow}M USD\nAcumulado: {STORE.btc_etf_inflows.get('acumulado_millones', 0)}M")

        pct_umbral = alertas_cfg.get("ormuz_cambio_transitos_pct", 20)
        transitos = STORE.ormuz.get("transitos_24h", 0)
        anterior = STORE.ormuz.get("transitos_anterior", 0)
        if anterior and transitos:
            cambio_pct = abs((transitos - anterior) / anterior * 100)
            if cambio_pct > pct_umbral:
                await self.enviar("ormuz", f"🚢 Ormuz: Tránsitos cambiaron {cambio_pct:.0f}%\nAnterior: {anterior} → Actual: {transitos}\nEstado: {STORE.ormuz.get('estado', '?')}")

        niveles = alertas_cfg.get("niveles_precio", {})
        for simbolo, limits in niveles.items():
            precio = STORE.precios.get(simbolo, {}).get("precio", 0)
            if precio <= 0: continue
            if precio >= limits.get("arriba", float("inf")):
                await self.enviar(f"precio_arriba_{simbolo}", f"📈 {simbolo}: ${precio:,.2f} cruzó nivel superior ${limits['arriba']:,.2f}")
            if precio <= limits.get("abajo", 0):
                await self.enviar(f"precio_abajo_{simbolo}", f"📉 {simbolo}: ${precio:,.2f} cruzó nivel inferior ${limits['abajo']:,.2f}")

alerter = AlertaTelegram()

async def loop_alertas():
    while True:
        await alerter.verificar_alertas()
        await asyncio.sleep(30)
