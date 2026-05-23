"""
brokers/bingx.py
Conexión directa a BingX API REST.
Firma HMAC SHA256 validada contra VST Demo.
"""
import hmac
import hashlib
import uuid
import requests
from config.settings import BINGX_API_KEY, BINGX_API_SECRET, BINGX_BASE_URL, SIMULATION_MODE, BINGX_ENV, ORDER_TIMEOUT
from utils.time_utils import now_ms
from logs.logger import get_logger
from brokers.market_info import round_qty

logger = get_logger(__name__)


# ============================================================
# 🔄 NORMALIZACIÓN SÍMBOLO TV → BINGX
# ============================================================
# TradingView envía símbolos en formato exchange: PENGUUSDT.P, BTCUSDT.P
# BingX Swap API espera:                          PENGU-USDT, BTC-USDT
#
# Regla general: quitar sufijo .P, insertar guión antes de USDT/BUSD/BTC
# Tabla de excepciones para pares que no siguen el patrón estándar.

_SYMBOL_EXCEPTIONS: dict[str, str] = {
    # "TVFORMAT": "BINGX-FORMAT",
    # Añadir aquí si algún par no normaliza bien automáticamente
}

def normalize_symbol(symbol: str) -> str:
    """
    Convierte símbolo TradingView a formato BingX.
    PENGUUSDT.P  → PENGU-USDT
    BTCUSDT.P    → BTC-USDT
    1000PEPEUSDT.P → 1000PEPE-USDT
    Si ya tiene guión se devuelve tal cual.
    """
    # Limpiar sufijos de TradingView
    clean = symbol.upper().replace(".P", "").replace(".PERP", "").strip()

    # Si ya está en formato BingX (tiene guión) no tocar
    if "-" in clean:
        return clean

    # Tabla de excepciones primero
    if clean in _SYMBOL_EXCEPTIONS:
        return _SYMBOL_EXCEPTIONS[clean]

    # Regla automática: insertar guión antes de las quote currencies conocidas
    for quote in ("USDT", "BUSD", "USDC", "BTC", "ETH"):
        if clean.endswith(quote):
            base = clean[: -len(quote)]
            if base:
                result = f"{base}-{quote}"
                logger.debug(f"🔄 Símbolo normalizado: {symbol} → {result}")
                return result

    # Si no se pudo normalizar, devolver limpio y loguear aviso
    logger.warning(f"⚠️ Símbolo no normalizado: {symbol} → {clean} (usando tal cual)")
    return clean


# ============================================================
# 🔐 FIRMA HMAC SHA256
# ============================================================

def _build_query(params: dict) -> str:
    sorted_qs = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
    return sorted_qs + "&timestamp=" + str(now_ms())

def _sign(query_string: str) -> str:
    return hmac.new(
        BINGX_API_SECRET.encode("utf-8"),
        query_string.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()

def _headers() -> dict:
    return {"X-BX-APIKEY": BINGX_API_KEY, "Content-Type": "application/json"}

def _get(path: str, params: dict) -> dict:
    try:
        qs = _build_query(params)
        sig = _sign(qs)
        url = f"{BINGX_BASE_URL}{path}?{qs}&signature={sig}"
        response = requests.get(url, headers=_headers(), timeout=ORDER_TIMEOUT)
        return response.json()
    except Exception as e:
        logger.error(f"❌ GET {path} error: {e}")
        return {}

def _post(path: str, params: dict) -> dict:
    try:
        qs = _build_query(params)
        sig = _sign(qs)
        url = f"{BINGX_BASE_URL}{path}?{qs}&signature={sig}"
        logger.info(f"📤 POST {path} | params={params} | qs={qs[:120]}...")
        response = requests.post(url, headers=_headers(), data=b"", timeout=ORDER_TIMEOUT)
        return response.json()
    except Exception as e:
        logger.error(f"❌ POST {path} error: {e}")
        return {}


# ============================================================
# 📊 CONSULTAS
# ============================================================

def get_balance() -> dict:
    data = _get("/openApi/swap/v2/user/balance", {"currency": "USDT"})
    if data.get("code") == 0:
        bal = data.get("data", {}).get("balance", {})
        logger.info(f"💰 [{BINGX_ENV.upper()}] Balance — equity={bal.get('equity')} available={bal.get('availableMargin')} USDT")
    else:
        logger.error(f"❌ Balance error: code={data.get('code')} msg={data.get('msg')}")
    return data

def get_positions(symbol: str = "") -> dict:
    params = {}
    if symbol:
        params["symbol"] = normalize_symbol(symbol)
    data = _get("/openApi/swap/v2/user/positions", params)
    if data.get("code") == 0:
        positions = [p for p in (data.get("data") or []) if float(p.get("positionAmt", 0)) != 0]
        logger.info(f"📋 [{BINGX_ENV.upper()}] Posiciones abiertas: {len(positions)}")
    else:
        logger.error(f"❌ Positions error: code={data.get('code')} msg={data.get('msg')}")
    return data


# ============================================================
# 🚀 ÓRDENES
# ============================================================

def place_order(
    symbol: str,
    side: str,
    quantity: float,
    position_side: str = "LONG",
    price_signal: float = None,
    robot: str = ""
) -> dict:
    """
    Coloca una orden de mercado.
    side:          BUY | SELL
    position_side: LONG | SHORT (Hedge Mode obligatorio)
    """
    if SIMULATION_MODE:
        logger.info(f"🧪 SIMULATION — [{robot}] {side} {quantity} {symbol} [{position_side}]")
        return {
            "simulation": True,
            "code": 0,
            "robot": robot,
            "side": side,
            "qty": quantity,
            "symbol": symbol,
            "position_side": position_side,
        }

    symbol = normalize_symbol(symbol)
    quantity = round_qty(symbol, quantity)   # precisión y mínimo según contrato
    client_order_id = str(uuid.uuid4())
    params = {
        "clientOrderID": client_order_id,
        "positionSide":  position_side,
        "quantity":      str(quantity),
        "side":          side,
        "symbol":        symbol,
        "type":          "MARKET",
    }

    data = _post("/openApi/swap/v2/trade/order", params)
    code = data.get("code")

    if code == 0:
        order = data.get("data", {}).get("order", {})
        price_executed = float(order.get("avgPrice", 0) or 0)
        qty_executed   = float(order.get("executedQty", quantity) or quantity)
        commission     = float(order.get("commission", 0) or 0)

        slippage = None
        if price_signal and price_executed:
            slippage = round(price_executed - float(price_signal), 8)

        logger.info(
            f"✅ [{BINGX_ENV.upper()}][{robot}] ORDER OK — {side} {position_side} {symbol} "
            f"qty={qty_executed} price={price_executed} "
            f"slip={slippage} commission={commission} USDT "
            f"orderId={order.get('orderId')} clientId={client_order_id}"
        )

        data["_meta"] = {
            "robot":            robot,
            "symbol":           symbol,
            "side":             side,
            "position_side":    position_side,
            "qty_executed":     qty_executed,
            "price_signal":     price_signal,
            "price_executed":   price_executed,
            "slippage":         slippage,
            "commission":       commission,
            "commission_asset": order.get("commissionAsset", "USDT"),
            "order_id":         order.get("orderId"),
            "client_order_id":  client_order_id,
        }
    else:
        logger.error(
            f"❌ [{BINGX_ENV.upper()}][{robot}] ORDER FAILED — {side} {position_side} {symbol} "
            f"qty={quantity} code={code} msg={data.get('msg')} clientId={client_order_id}"
        )

    return data


def close_position(
    symbol: str,
    position_side: str,
    quantity: float = None,
    price_signal: float = None,
    robot: str = ""
) -> dict:
    """
    Cierra una posición (total o parcial).
    Si quantity=None, consulta qty real en BingX antes de cerrar.
    """
    if SIMULATION_MODE:
        logger.info(f"🧪 SIMULATION — [{robot}] CLOSE {position_side} {symbol} qty={quantity}")
        return {"simulation": True, "code": 0, "action": "close", "position_side": position_side, "symbol": symbol}

    if quantity is None:
        pos_data = get_positions(symbol)
        positions = pos_data.get("data") or []
        pos = next(
            (p for p in positions
             if p.get("positionSide") == position_side and float(p.get("positionAmt", 0)) > 0),
            None
        )
        if not pos:
            logger.warning(f"⚠️ [{robot}] CLOSE {position_side} {symbol} — no hay posición abierta")
            return {"code": -1, "msg": "no_open_position"}
        quantity = abs(float(pos.get("positionAmt", 0)))

    close_side = "SELL" if position_side == "LONG" else "BUY"
    return place_order(
        symbol=symbol,
        side=close_side,
        quantity=quantity,
        position_side=position_side,
        price_signal=price_signal,
        robot=robot,
    )


# ============================================================
# 🔧 ALIAS compatibilidad con signal_handler existente
# ============================================================
def close_all_positions(symbol: str, side: str, robot: str = "") -> dict:
    """side aquí es positionSide: LONG | SHORT"""
    return close_position(symbol=symbol, position_side=side, robot=robot)
