import json
from pathlib import Path

RUTA_CONFIG = Path(__file__).parent.parent.parent / "config.json"

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
    if not RUTA_CONFIG.exists():
        with open(RUTA_CONFIG, "w", encoding="utf-8") as f:
            json.dump(CONFIG_DEFAULT, f, indent=4, ensure_ascii=False)
    with open(RUTA_CONFIG, "r", encoding="utf-8") as f:
        return json.load(f)

config = cargar_config()
