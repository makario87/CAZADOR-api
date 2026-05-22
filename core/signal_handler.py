"""
core/signal_handler.py
Interpreta las señales de CAZADOR y las ejecuta en el broker.
TradingView es el cerebro. Python es el ejecutor.
"""
import time
from brokers.bingx import place_order, close_all_positions
from data.state import get_state, update_state, update_position
from core.emergency import trigger_emergency
from config.settings import GIRO_BUFFER_SECONDS, DEMO_MODE
from logs.logger import get_logger
from data.trade_log import log_trade

logger = get_logger(__name__)

# ============================================================
# 🎯 SEÑALES VÁLIDAS
# ============================================================
VALID_SIGNALS = {
    "ENTRY_LONG", "ENTRY_SHORT",
    "CLOSE_LONG", "CLOSE_SHORT",
    "GIRO_LONG", "GIRO_SHORT",
    "SL_LONG_DYNAMIC", "SL_SHORT_DYNAMIC",
    "SL_LONG_BLACK", "SL_SHORT_BLACK",
    "SL_LONG_CCI", "SL_SHORT_CCI",
    "SL_LONG_PROMEDIO", "SL_SHORT_PROMEDIO",
    "SL_LONG_LAST", "SL_SHORT_LAST",
}

# ============================================================
# 🚀 DISPATCHER PRINCIPAL
# ============================================================
def handle_signal(payload: dict) -> dict:
    """
    Punto de entrada principal para todas las señales de CAZADOR.
    Recibe el JSON parseado de TradingView y lo ejecuta.
    """
    signal = payload.get("signal", "").upper()
    symbol = payload.get("symbol", "")
    qty    = float(payload.get("qty", 0))
    price  = payload.get("price", "0")

    logger.info(f"📨 Señal recibida: {signal} | {symbol} | qty={qty} | price={price}")

    # Validar señal
    if signal not in VALID_SIGNALS:
        logger.warning(f"⚠️ Señal desconocida ignorada: {signal}")
        return {"status": "ignored", "reason": "unknown_signal"}

    # Verificar emergencia activa
    state = get_state()
    if state.get("emergency"):
        logger.error(f"🚨 EMERGENCIA ACTIVA — señal bloqueada: {signal}")
        return {"status": "blocked", "reason": "emergency_active"}

    # Dispatcher
    try:
        if signal == "ENTRY_LONG":
            return _entry_long(symbol, qty, payload)

        elif signal == "ENTRY_SHORT":
            return _entry_short(symbol, qty, payload)

        elif signal == "CLOSE_LONG":
            return _close_long(symbol, payload)

        elif signal == "CLOSE_SHORT":
            return _close_short(symbol, payload)

        elif signal == "GIRO_LONG":
            return _giro_long(symbol, qty, payload)

        elif signal == "GIRO_SHORT":
            return _giro_short(symbol, qty, payload)

        elif signal.startswith("SL_LONG"):
            return _sl_long(symbol, signal, payload)

        elif signal.startswith("SL_SHORT"):
            return _sl_short(symbol, signal, payload)

    except Exception as e:
        logger.error(f"❌ Error ejecutando señal {signal}: {e}")
        trigger_emergency(f"Error ejecutando {signal}: {e}")
        return {"status": "error", "reason": str(e)}

    return {"status": "ok"}

# ============================================================
# 📈 ENTRADAS
# ============================================================
def _entry_long(symbol: str, qty: float, payload: dict = None) -> dict:
    logger.info(f"🟢 ENTRY_LONG {symbol} qty={qty}")

    result = place_order(symbol, "BUY", qty, "LONG")

    log_trade(
        signal = "ENTRY_LONG",
        symbol = symbol,
        qty    = qty,
        price  = payload.get("price", "0") if payload else "0",
        result = result,
        robot  = payload.get("robot", "CAZADOR") if payload else "CAZADOR",
        demo   = DEMO_MODE,
    )

    update_state({"last_signal": "ENTRY_LONG", "symbol": symbol})
    update_position(symbol, has_long=True, has_short=False)

    return {
        "status": "ok",
        "action": "ENTRY_LONG",
        "result": result
    }

def _entry_short(symbol: str, qty: float, payload: dict = None) -> dict:
    logger.info(f"🔴 ENTRY_SHORT {symbol} qty={qty}")

    result = place_order(symbol, "SELL", qty, "SHORT")

    log_trade(
        signal = "ENTRY_SHORT",
        symbol = symbol,
        qty    = qty,
        price  = payload.get("price", "0") if payload else "0",
        result = result,
        robot  = payload.get("robot", "CAZADOR") if payload else "CAZADOR",
        demo   = DEMO_MODE,
    )

    update_state({"last_signal": "ENTRY_SHORT", "symbol": symbol})
    update_position(symbol, has_long=False, has_short=True)

    return {
        "status": "ok",
        "action": "ENTRY_SHORT",
        "result": result
    }

# ============================================================
# 📉 CIERRES
# ============================================================
def _close_long(symbol: str, payload: dict = None) -> dict:
    logger.info(f"⬜ CLOSE_LONG {symbol}")

    result = close_all_positions(symbol, "LONG")

    log_trade(
        signal = "CLOSE_LONG",
        symbol = symbol,
        qty    = 0,
        price  = payload.get("price", "0") if payload else "0",
        result = result,
        robot  = payload.get("robot", "CAZADOR") if payload else "CAZADOR",
        demo   = DEMO_MODE,
    )

    update_state({"last_signal": "CLOSE_LONG", "symbol": symbol})
    update_position(symbol, has_long=False, has_short=False)

    return {
        "status": "ok",
        "action": "CLOSE_LONG",
        "result": result
    }

def _close_short(symbol: str, payload: dict = None) -> dict:
    logger.info(f"⬜ CLOSE_SHORT {symbol}")

    result = close_all_positions(symbol, "SHORT")

    log_trade(
        signal = "CLOSE_SHORT",
        symbol = symbol,
        qty    = 0,
        price  = payload.get("price", "0") if payload else "0",
        result = result,
        robot  = payload.get("robot", "CAZADOR") if payload else "CAZADOR",
        demo   = DEMO_MODE,
    )

    update_state({"last_signal": "CLOSE_SHORT", "symbol": symbol})
    update_position(symbol, has_long=False, has_short=False)

    return {
        "status": "ok",
        "action": "CLOSE_SHORT",
        "result": result
    }

# ============================================================
# 🔄 GIROS
# ============================================================
def _giro_long(symbol: str, qty: float, payload: dict) -> dict:
    logger.info(f"🔄 GIRO_LONG {symbol}")
    
    qty_close = float(payload.get("qty_close", qty))
    qty_open  = float(payload.get("qty_open", qty))
    
    logger.info(f"   qty_close={qty_close} qty_open={qty_open}")
    
    result_close = close_all_positions(symbol, "SHORT")
    time.sleep(GIRO_BUFFER_SECONDS)
    result_open  = place_order(symbol, "BUY", qty_open, "LONG")
    
    log_trade(
        signal = "GIRO_LONG_CLOSE",
        symbol = symbol,
        qty    = qty_close,
        price  = payload.get("price", "0"),
        result = result_close,
        robot  = payload.get("robot", "CAZADOR"),
        demo   = DEMO_MODE,
    )
    
    log_trade(
        signal = "GIRO_LONG_OPEN",
        symbol = symbol,
        qty    = qty_open,
        price  = payload.get("price", "0"),
        result = result_open,
        robot  = payload.get("robot", "CAZADOR"),
        demo   = DEMO_MODE,
    )
    
    update_state({"last_signal": "GIRO_LONG", "symbol": symbol})
    update_position(symbol, has_long=True, has_short=False)
    return {"status": "ok", "action": "GIRO_LONG", "close": result_close, "open": result_open}


def _giro_short(symbol: str, qty: float, payload: dict) -> dict:
    logger.info(f"🔄 GIRO_SHORT {symbol}")
    
    qty_close = float(payload.get("qty_close", qty))
    qty_open  = float(payload.get("qty_open", qty))
    
    logger.info(f"   qty_close={qty_close} qty_open={qty_open}")
    
    result_close = close_all_positions(symbol, "LONG")
    time.sleep(GIRO_BUFFER_SECONDS)
    result_open  = place_order(symbol, "SELL", qty_open, "SHORT")
    log_trade(
        signal = "GIRO_SHORT_CLOSE",
        symbol = symbol,
        qty    = qty_close,
        price  = payload.get("price", "0"),
        result = result_close,
        robot  = payload.get("robot", "CAZADOR"),
        demo   = DEMO_MODE,
    )
    
    log_trade(
        signal = "GIRO_SHORT_OPEN",
        symbol = symbol,
        qty    = qty_open,
        price  = payload.get("price", "0"),
        result = result_open,
        robot  = payload.get("robot", "CAZADOR"),
        demo   = DEMO_MODE,
    )
    
    update_state({"last_signal": "GIRO_SHORT", "symbol": symbol})
    update_position(symbol, has_long=False, has_short=True)
    return {"status": "ok", "action": "GIRO_SHORT", "close": result_close, "open": result_open}

# ============================================================
# 🛑 STOP LOSS
# ============================================================
def _sl_long(symbol: str, signal: str, payload: dict = None) -> dict:
    logger.info(f"🛑 {signal} {symbol} — cerrando LONG completo")

    result = close_all_positions(symbol, "LONG")

    log_trade(
        signal = signal,
        symbol = symbol,
        qty    = 0,
        price  = payload.get("price", "0") if payload else "0",
        result = result,
        robot  = payload.get("robot", "CAZADOR") if payload else "CAZADOR",
        demo   = DEMO_MODE,
    )

    update_state({"last_signal": signal, "symbol": symbol})
    update_position(symbol, has_long=False, has_short=False)

    return {
        "status": "ok",
        "action": signal,
        "result": result
    }

def _sl_short(symbol: str, signal: str, payload: dict = None) -> dict:
    logger.info(f"🛑 {signal} {symbol} — cerrando SHORT completo")

    result = close_all_positions(symbol, "SHORT")

    log_trade(
        signal = signal,
        symbol = symbol,
        qty    = 0,
        price  = payload.get("price", "0") if payload else "0",
        result = result,
        robot  = payload.get("robot", "CAZADOR") if payload else "CAZADOR",
        demo   = DEMO_MODE,
    )

    update_state({"last_signal": signal, "symbol": symbol})
    update_position(symbol, has_long=False, has_short=False)

    return {
        "status": "ok",
        "action": signal,
        "result": result
    }
