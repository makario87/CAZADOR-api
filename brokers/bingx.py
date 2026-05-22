"""
brokers/bingx.py
Conexión directa a BingX API REST.
Usa requests + HMAC SHA256. Sin CCXT.
"""
import hmac
import hashlib
import requests
from config.settings import BINGX_API_KEY, BINGX_API_SECRET, BINGX_BASE_URL, DEMO_MODE
from utils.time_utils import now_ms
from logs.logger import get_logger

logger = get_logger(__name__)

# ============================================================
# 🔐 FIRMA HMAC SHA256
# ============================================================
def _sign(params: dict) -> str:
    query = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
    return hmac.new(
        BINGX_API_SECRET.encode("utf-8"),
        query.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()

def _headers() -> dict:
    return {
        "X-BX-APIKEY": BINGX_API_KEY,
        "Content-Type": "application/json"
    }

# ============================================================
# 📊 CONSULTAS
# ============================================================
def get_balance() -> dict:
    """Consulta balance disponible en cuenta de futuros."""
    try:
        params = {"timestamp": now_ms()}
        params["signature"] = _sign(params)
        url = f"{BINGX_BASE_URL}/openApi/swap/v2/user/balance"
        response = requests.get(url, headers=_headers(), params=params, timeout=5)
        data = response.json()
        logger.info(f"💰 Balance consultado: {data}")
        return data
    except Exception as e:
        logger.error(f"❌ Error consultando balance: {e}")
        return {}

def get_positions(symbol: str = "") -> dict:
    """Consulta posiciones abiertas."""
    try:
        params = {"timestamp": now_ms()}
        if symbol:
            params["symbol"] = symbol
        params["signature"] = _sign(params)
        url = f"{BINGX_BASE_URL}/openApi/swap/v2/user/positions"
        response = requests.get(url, headers=_headers(), params=params, timeout=5)
        data = response.json()
        logger.info(f"📋 Posiciones consultadas: {data}")
        return data
    except Exception as e:
        logger.error(f"❌ Error consultando posiciones: {e}")
        return {}

# ============================================================
# 🚀 ÓRDENES
# ============================================================
def place_order(symbol: str, side: str, quantity: float, position_side: str = "LONG") -> dict:
    """
    Coloca una orden de mercado.
    side: BUY | SELL
    position_side: LONG | SHORT (Hedge Mode)
    """
    if DEMO_MODE:
        logger.info(f"🧪 DEMO MODE — Orden simulada: {side} {quantity} {symbol} [{position_side}]")
        return {"demo": True, "side": side, "qty": quantity, "symbol": symbol}

    try:
        params = {
            "symbol": symbol,
            "side": side,
            "positionSide": position_side,
            "type": "MARKET",
            "quantity": quantity,
            "timestamp": now_ms()
        }
        params["signature"] = _sign(params)
        url = f"{BINGX_BASE_URL}/openApi/swap/v2/trade/order"
        response = requests.post(url, headers=_headers(), params=params, timeout=5)
        data = response.json()
        logger.info(f"✅ Orden ejecutada: {data}")
        return data
    except Exception as e:
        logger.error(f"❌ Error ejecutando orden: {e}")
        return {}

def close_all_positions(symbol: str, side: str) -> dict:
    """
    Cierra TODA la posición de un lado (LONG o SHORT).
    Usado en CLOSE_LONG, CLOSE_SHORT, GIROS y SL.
    """
    if DEMO_MODE:
        logger.info(f"🧪 DEMO MODE — Cierre simulado: {side} {symbol}")
        return {"demo": True, "action": "close", "side": side, "symbol": symbol}

    try:
        params = {
            "symbol": symbol,
            "positionSide": side,
            "type": "MARKET",
            "timestamp": now_ms()
        }
        params["signature"] = _sign(params)
        url = f"{BINGX_BASE_URL}/openApi/swap/v2/trade/closePosition"
        response = requests.post(url, headers=_headers(), params=params, timeout=5)
        data = response.json()
        logger.info(f"✅ Posición cerrada: {data}")
        return data
    except Exception as e:
        logger.error(f"❌ Error cerrando posición: {e}")
        return {}
