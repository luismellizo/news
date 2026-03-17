class DataStore:
    def __init__(self):
        self.precios = {
            "SPY": {"precio": 0.0, "cambio_pct": 0.0, "volumen": 0, "ts": ""},
            "BINANCE:BTCUSDT": {"precio": 0.0, "cambio_pct": 0.0, "volumen": 0, "ts": ""},
            "USO": {"precio": 0.0, "cambio_pct": 0.0, "volumen": 0, "ts": ""},
        }
        self.precios_cierre = {}

        self.btc_etf_inflows = {
            "net_flow_hoy_millones": 0.0,
            "acumulado_millones": 0.0,
            "detalle": [],
            "ultima_actualizacion": "Sin datos",
            "error": ""
        }

        self.yields = {
            "TNX": {
                "valor": 0.0,
                "cambio_bps": 0.0,
                "cambio_pct": 0.0,
                "ultima_actualizacion": "Sin datos",
                "error": ""
            }
        }
        
        self.correlaciones = {
            "spy_btc_60m": 0.0,
            "spy_uso_60m": 0.0,
            "ultima_actualizacion": "Calculando..."
        }

        self.macro = {
            "noticias": [],
            "sentiment_score": 0.0,
            "ultima_actualizacion": "Sin datos",
            "error": ""
        }

        self.ws_conectado = False
        self.usando_fallback = False
        self.alertas_enviadas = {}
        self.finnhub_ws_conn = None
        
        self.historial_precios = {
            "SPY": [],
            "BINANCE:BTCUSDT": [],
            "USO": [],
        }

STORE = DataStore()
