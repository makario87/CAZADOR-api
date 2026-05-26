"""
brokers/bingx.py
Conexión directa a BingX API REST.
Firma HMAC SHA256 validada contra VST Demo.
"""
import hmac
import hashlib
import time
import uuid
import requests
from config.settings import BINGX_API_KEY, BINGX_API_SECRET, BINGX_BASE_URL, SIMULATION_MODE, BINGX_ENV, ORDER_TIMEOUT
from utils.time_utils import now_ms
from logs.logger import get_logger
from brokers.market_info import round_qty, format_qty

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

    # NUEVO: símbolo vacío → salir silenciosamente
    if not symbol or not symbol.strip():
        return ""

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
    return {"X-BX-APIKEY": BINGX_API_KEY}

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


# ============================================================
# 🔁 RETRY — códigos de error temporales de BingX
# ============================================================
# Estos errores son transitorios: BingX estaba saturado o hubo
# un corte de red puntual. Merece reintentar, no emergencia.
# Cualquier otro código de error es permanente → salida inmediata.

_RETRYABLE_CODES = {101500}   # "system busy"
_RETRY_ATTEMPTS  = 3
_RETRY_DELAY     = 0.5        # segundos entre intentos


def _post(path: str, params: dict) -> dict:
    """
    POST a BingX con retry automático para errores temporales.

    Flujo:
      - Intenta hasta _RETRY_ATTEMPTS veces.
      - Si code == 0                → éxito, return data inmediato.
      - Si code en _RETRYABLE_CODES → espera _RETRY_DELAY y reintenta.
      - Si code es otro error        → error permanente, return inmediato.
      - Si excepción de red          → cuenta como intento, reintenta.
      - Si agota todos los intentos  → return último data (o {}).
    """
    last_data = {}

    for attempt in range(1, _RETRY_ATTEMPTS + 1):
        try:
            qs  = _build_query(params)
            sig = _sign(qs)
            url = f"{BINGX_BASE_URL}{path}?{qs}&signature={sig}"

            if attempt == 1:
                logger.info(f"📤 POST {path} | params={params} | qs={qs[:120]}...")
            else:
                logger.warning(f"🔁 POST {path} — reintento {attempt}/{_RETRY_ATTEMPTS}")

            response = requests.post(url, headers=_headers(), data={}, timeout=ORDER_TIMEOUT)
            data     = response.json()
            code     = data.get("code")
            last_data = data

            if code == 0:
                # Éxito
                return data

            if code in _RETRYABLE_CODES:
                # Error temporal → reintenta si quedan intentos
                logger.warning(
                    f"⚠️ POST {path} — error temporal code={code} msg={data.get('msg')} "
                    f"(intento {attempt}/{_RETRY_ATTEMPTS})"
                )
                if attempt < _RETRY_ATTEMPTS:
                    time.sleep(_RETRY_DELAY)
                continue

            # Error permanente → salir inmediatamente sin más intentos
            logger.error(
                f"❌ POST {path} — error permanente code={code} msg={data.get('msg')} "
                f"(intento {attempt}/{_RETRY_ATTEMPTS})"
            )
            return data

        except requests.exceptions.Timeout:
            logger.warning(
                f"⚠️ POST {path} — timeout (intento {attempt}/{_RETRY_ATTEMPTS})"
            )
            if attempt < _RETRY_ATTEMPTS:
                time.sleep(_RETRY_DELAY)

        except requests.exceptions.ConnectionError:
            logger.warning(
                f"⚠️ POST {path} — connection error (intento {attempt}/{_RETRY_ATTEMPTS})"
            )
            if attempt < _RETRY_ATTEMPTS:
                time.sleep(_RETRY_DELAY)

        except Exception as e:
            logger.error(f"❌ POST {path} — excepción inesperada: {e}")
            return last_data

    # Agotados todos los intentos sin éxito
    logger.error(
        f"❌ POST {path} — agotados {_RETRY_ATTEMPTS} intentos. "
        f"Último code={last_data.get('code')} msg={last_data.get('msg')}"
    )
    return last_data


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

def ping_bingx() -> bool:
    """
    Comprueba conectividad básica con BingX.
    Retorna True si BingX responde code=0, False si no.
    Usado por el watchdog en emergency.py.
    """

    try:

        data = _get(
            "/openApi/swap/v2/user/balance",
            {"currency": "USDT"}
        )

        ok = data.get("code") == 0

        if not ok:

            logger.warning(
                f"⚠️ ping_bingx — "
                f"code={data.get('code')} "
                f"msg={data.get('msg')}"
            )

        return ok

    except Exception as e:

        logger.error(
            f"❌ ping_bingx — excepción: {e}"
        )

        return False

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

def get_order_history(symbol: str, limit: int = 20) -> list:
    """
    Devuelve las últimas N órdenes cerradas/ejecutadas en BingX para un símbolo.
    Usado por reconciler.py para detectar cierres manuales.
    
    Endpoint: GET /openApi/swap/v2/trade/allOrders
    Retorna: lista de órdenes (puede estar vacía si falla)
    Cada orden incluye: orderId, clientOrderId, side, positionSide, status, etc.
    """
    params = {
        "symbol": normalize_symbol(symbol),
        "limit":  limit,
    }
    data = _get("/openApi/swap/v2/trade/allOrders", params)

    if data.get("code") == 0:
        orders = data.get("data", {}).get("orders") or []
        logger.info(
            f"📜 [{BINGX_ENV.upper()}] Historial órdenes {normalize_symbol(symbol)} "
            f"— {len(orders)} registros"
        )
        return orders
    else:
        logger.error(
            f"❌ get_order_history {normalize_symbol(symbol)} — "
            f"code={data.get('code')} msg={data.get('msg')}"
        )
        return [] 


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
    qty_str = format_qty(symbol, quantity)
    params = {
        "clientOrderID": client_order_id,
        "positionSide":  position_side,
        "quantity":      qty_str,
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
        # Registrar nuestro clientOrderID para detección de cierres manuales
        from data.state import register_our_order
        register_our_order(client_order_id)
    else:
        logger.error(
            f"❌ [{BINGX_ENV.upper()}][{robot}] ORDER FAILED — {side} {position_side} {symbol} "
            f"qty={quantity} code={code} msg={data.get('msg')} clientId={client_order_id}"
        )

    return data

# ============================================================
# 🛡️ SL BROKER — STOP_MARKET RED DE SEGURIDAD
# ============================================================

def place_stop_order(
    symbol: str,
    side: str,           # BUY para cerrar SHORT | SELL para cerrar LONG
    position_side: str,  # LONG | SHORT
    stop_price: float,
    quantity: float,
    robot: str = ""
) -> dict:
    """
    Coloca una orden STOP_MARKET como red de seguridad (SL broker).

    IMPORTANTE:
    - SOLO se llama después de confirmar entrada OK.
    - NO activa emergencia si falla.
    - TV sigue siendo la fuente de verdad.
    """

    if SIMULATION_MODE:
        logger.info(
            f"🧪 SIMULATION — [{robot}] STOP_MARKET "
            f"{side} {symbol} stop={stop_price} qty={quantity}"
        )
        return {
            "simulation": True,
            "code": 0
        }

    symbol = normalize_symbol(symbol)

    quantity = round_qty(symbol, quantity)
    qty_str  = format_qty(symbol, quantity)

    client_order_id = str(uuid.uuid4())

    params = {
        "clientOrderID": client_order_id,
        "positionSide":  position_side,
        "quantity":      qty_str,
        "side":          side,
        "symbol":        symbol,
        "type":          "STOP_MARKET",
        "stopPrice":     str(round(stop_price, 8)),
    }

    data = _post("/openApi/swap/v2/trade/order", params)

    code = data.get("code")

    if code == 0:

        logger.info(
            f"✅ [{BINGX_ENV.upper()}][{robot}] SL BROKER OK — "
            f"{side} {position_side} {symbol} "
            f"stop={stop_price} qty={quantity} "
            f"clientId={client_order_id}"
        )
        order = data.get("data", {}).get("order", {})

        data["_meta"] = {
            "order_id":        order.get("orderId"),
            "client_order_id": client_order_id,
        }

    else:

        logger.error(
            f"❌ [{BINGX_ENV.upper()}][{robot}] SL BROKER FAILED — "
            f"{side} {position_side} {symbol} "
            f"stop={stop_price} "
            f"code={code} msg={data.get('msg')} "
            f"clientId={client_order_id}"
        )

    return data

# ============================================================
# 🗑️ CANCELAR ORDEN — STOP BROKER REFRESH
# ============================================================

def cancel_order(symbol: str, order_id: str, robot: str = "") -> dict:
    """
    Cancela una orden pendiente por orderId.

    Usado para:
    cancelar STOP_MARKET anterior antes de colocar uno nuevo.

    IMPORTANTE:
    - Si ya ejecutó o no existe → solo warning.
    - NO activa emergency.
    """

    if SIMULATION_MODE:
        logger.info(
            f"🧪 SIMULATION — [{robot}] CANCEL "
            f"order_id={order_id} {symbol}"
        )
        return {
            "simulation": True,
            "code": 0
        }

    symbol = normalize_symbol(symbol)

    params = {
        "symbol":  symbol,
        "orderId": order_id,
    }

    try:

        qs  = _build_query(params)
        sig = _sign(qs)

        url = (
            f"{BINGX_BASE_URL}"
            f"/openApi/swap/v2/trade/order"
            f"?{qs}&signature={sig}"
        )

        logger.info(
            f"🗑️ [{robot}] CANCEL "
            f"order_id={order_id} {symbol}"
        )

        response = requests.delete(
            url,
            headers=_headers(),
            timeout=ORDER_TIMEOUT
        )

        data = response.json()
        code = data.get("code")

        if code == 0:

            logger.info(
                f"✅ [{BINGX_ENV.upper()}][{robot}] CANCEL OK — "
                f"order_id={order_id} {symbol}"
            )

        else:

            logger.warning(
                f"⚠️ [{BINGX_ENV.upper()}][{robot}] CANCEL no ejecutado — "
                f"order_id={order_id} {symbol} "
                f"code={code} msg={data.get('msg')} "
                f"(puede que ya ejecutó o no existía)"
            )

        return data

    except Exception as e:

        logger.error(
            f"❌ [{robot}] Excepción en cancel_order: {e}"
        )

        return {}


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
        return {
            "simulation": True,
            "code": 0,
            "action": "close",
            "position_side": position_side,
            "symbol": symbol
        }
    
    if quantity is None:
        pos_data = get_positions(symbol)
        positions = pos_data.get("data") or []
    
        logger.info(f"🔍 [{robot}] Buscando {position_side} entre {len(positions)} posiciones para {symbol}")
    
        for p in positions:
            logger.debug(
                f"   → symbol={p.get('symbol')} "
                f"side={p.get('positionSide')} "
                f"amt={p.get('positionAmt')}"
            )
    
        pos = next(
            (p for p in positions
             if p.get("positionSide") == position_side
             and abs(float(p.get("positionAmt", 0))) > 0),
            None
        )
    
        if not pos:
            logger.warning(f"⚠️ [{robot}] CLOSE {position_side} {symbol} — no hay posición abierta")
            return {"code": -1, "msg": "no_open_position"}
    
        quantity = abs(float(pos.get("positionAmt", 0)))
    
        logger.info(f"🔍 [{robot}] Posición encontrada: {position_side} qty={quantity}")

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
