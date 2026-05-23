"""
core/signal_handler.py
Interpreta las señales de CAZADOR y las ejecuta en el broker.
TradingView manda solo la señal. Python calcula la qty.
"""
import time
from brokers.bingx import place_order, close_all_positions, get_balance
from data.state import get_state, update_state, update_position, update_entry
from core.emergency import trigger_emergency
from config.settings import GIRO_BUFFER_SECONDS, SIMULATION_MODE, RISK_PCT
from logs.logger import get_logger
from data.trade_log import log_trade

logger = get_logger(__name__)

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
# 💰 SIZING — qty calculada en Python
# ============================================================

def _calculate_qty(price_str: str, robot: str = "") -> float:
    """
    Calcula qty en contratos usando balance real de BingX.

    Fórmula:
        margen    = balance_disponible × RISK_PCT
        qty       = margen / precio_actual

    BingX aplica el leverage configurado manualmente en el broker.
    Python solo decide cuánto margen arriesgar.

    Devuelve qty como float redondeado a 0 decimales (contratos enteros).
    En el futuro: step_size por símbolo para redondeo preciso.
    """
    try:
        price = float(price_str)
        if price <= 0:
            raise ValueError(f"Precio inválido: {price}")

        bal_data = get_balance()
        if bal_data.get("code") != 0:
            raise ValueError(f"Balance no disponible: {bal_data.get('msg')}")

        available = float(
            bal_data.get("data", {}).get("balance", {}).get("availableMargin", 0)
        )
        if available <= 0:
            raise ValueError(f"Balance disponible cero o negativo: {available}")

        margen = available * RISK_PCT
        qty    = margen / price

        # Redondear a entero — suficiente para la mayoría de pares
        # TODO futuro: step_size por símbolo desde BingX market info
        qty_rounded = max(1, round(qty))

        logger.info(
            f"💰 [{robot}] Sizing: balance={available:.2f} USDT "
            f"× {RISK_PCT*100:.1f}% = {margen:.2f} USDT margen "
            f"/ price={price} = {qty:.2f} → qty={qty_rounded}"
        )
        return float(qty_rounded)

    except Exception as e:
        logger.error(f"❌ [{robot}] Error calculando qty: {e}")
        return 0.0


# ============================================================
# 🚀 DISPATCHER PRINCIPAL
# ============================================================

def handle_signal(payload: dict) -> dict:
    signal = payload.get("signal", "").upper()
    symbol = payload.get("symbol", "")
    price  = payload.get("price", "0")
    robot  = payload.get("robot", "CAZADOR")

    # qty de TV ignorada para ENTRY — Python la calcula
    # Para CLOSE/SL/GIRO: qty viene de la posición real en BingX
    logger.info(f"📨 Señal recibida: {signal} | {symbol} | price={price} | robot={robot}")

    if signal not in VALID_SIGNALS:
        logger.warning(f"⚠️ Señal desconocida ignorada: {signal}")
        return {"status": "ignored", "reason": "unknown_signal"}

    state = get_state()
    if state.get("emergency"):
        logger.error(f"🚨 EMERGENCIA ACTIVA — señal bloqueada: {signal}")
        return {"status": "blocked", "reason": "emergency_active"}

    try:
        if signal == "ENTRY_LONG":
            return _entry_long(symbol, price, robot, payload)
        elif signal == "ENTRY_SHORT":
            return _entry_short(symbol, price, robot, payload)
        elif signal == "CLOSE_LONG":
            return _close_long(symbol, price, robot, payload)
        elif signal == "CLOSE_SHORT":
            return _close_short(symbol, price, robot, payload)
        elif signal == "GIRO_LONG":
            return _giro_long(symbol, price, robot, payload)
        elif signal == "GIRO_SHORT":
            return _giro_short(symbol, price, robot, payload)
        elif signal.startswith("SL_LONG"):
            return _sl_long(symbol, signal, price, robot, payload)
        elif signal.startswith("SL_SHORT"):
            return _sl_short(symbol, signal, price, robot, payload)

    except Exception as e:
        logger.error(f"❌ Error ejecutando señal {signal}: {e}")
        trigger_emergency(f"Error ejecutando {signal}: {e}")
        return {"status": "error", "reason": str(e)}

    return {"status": "ok"}


# ============================================================
# 📈 ENTRADAS — qty calculada por Python
# ============================================================

def _entry_long(symbol: str, price: str, robot: str, payload: dict) -> dict:
    qty = _calculate_qty(price, robot)
    if qty <= 0:
        return {"status": "error", "reason": "qty_calculation_failed"}

    logger.info(f"🟢 ENTRY_LONG {symbol} qty={qty} price={price} [{robot}]")
    result = place_order(symbol, "BUY", qty, "LONG", price_signal=float(price), robot=robot)

    log_trade(signal="ENTRY_LONG", symbol=symbol, qty=qty, price=price,
              result=result, robot=robot, demo=SIMULATION_MODE)
    update_state({"last_signal": "ENTRY_LONG", "symbol": symbol})
    update_position(symbol, has_long=True, has_short=False)

    # Guardar entrada para PnL futuro
    if result.get("code") == 0:
        price_exec = result.get("_meta", {}).get("price_executed") or float(price)
        update_entry("LONG", price_exec, qty)

    return {"status": "ok", "action": "ENTRY_LONG", "qty": qty, "result": result}


def _entry_short(symbol: str, price: str, robot: str, payload: dict) -> dict:
    qty = _calculate_qty(price, robot)
    if qty <= 0:
        return {"status": "error", "reason": "qty_calculation_failed"}

    logger.info(f"🔴 ENTRY_SHORT {symbol} qty={qty} price={price} [{robot}]")
    result = place_order(symbol, "SELL", qty, "SHORT", price_signal=float(price), robot=robot)

    log_trade(signal="ENTRY_SHORT", symbol=symbol, qty=qty, price=price,
              result=result, robot=robot, demo=SIMULATION_MODE)
    update_state({"last_signal": "ENTRY_SHORT", "symbol": symbol})
    update_position(symbol, has_long=False, has_short=True)

    if result.get("code") == 0:
        price_exec = result.get("_meta", {}).get("price_executed") or float(price)
        update_entry("SHORT", price_exec, qty)

    return {"status": "ok", "action": "ENTRY_SHORT", "qty": qty, "result": result}


# ============================================================
# 📉 CIERRES — qty leída de posición real en BingX
# ============================================================

def _close_long(symbol: str, price: str, robot: str, payload: dict) -> dict:
    logger.info(f"⬜ CLOSE_LONG {symbol} [{robot}]")
    result = close_all_positions(symbol, "LONG", robot=robot)
    log_trade(signal="CLOSE_LONG", symbol=symbol, qty=0, price=price,
              result=result, robot=robot, demo=SIMULATION_MODE)
    update_state({"last_signal": "CLOSE_LONG", "symbol": symbol})
    update_position(symbol, has_long=False, has_short=False)
    return {"status": "ok", "action": "CLOSE_LONG", "result": result}


def _close_short(symbol: str, price: str, robot: str, payload: dict) -> dict:
    logger.info(f"⬜ CLOSE_SHORT {symbol} [{robot}]")
    result = close_all_positions(symbol, "SHORT", robot=robot)
    log_trade(signal="CLOSE_SHORT", symbol=symbol, qty=0, price=price,
              result=result, robot=robot, demo=SIMULATION_MODE)
    update_state({"last_signal": "CLOSE_SHORT", "symbol": symbol})
    update_position(symbol, has_long=False, has_short=False)
    return {"status": "ok", "action": "CLOSE_SHORT", "result": result}


# ============================================================
# 🔄 GIROS
# ============================================================

def _giro_long(symbol: str, price: str, robot: str, payload: dict) -> dict:
    logger.info(f"🔄 GIRO_LONG {symbol} [{robot}]")

    result_close = close_all_positions(symbol, "SHORT", robot=robot)
    time.sleep(GIRO_BUFFER_SECONDS)

    qty = _calculate_qty(price, robot)
    if qty <= 0:
        return {"status": "error", "reason": "qty_calculation_failed"}

    result_open = place_order(symbol, "BUY", qty, "LONG", price_signal=float(price), robot=robot)

    log_trade(signal="GIRO_LONG_CLOSE", symbol=symbol, qty=0, price=price,
              result=result_close, robot=robot, demo=SIMULATION_MODE)
    log_trade(signal="GIRO_LONG_OPEN", symbol=symbol, qty=qty, price=price,
              result=result_open, robot=robot, demo=SIMULATION_MODE)

    update_state({"last_signal": "GIRO_LONG", "symbol": symbol})
    update_position(symbol, has_long=True, has_short=False)

    if result_open.get("code") == 0:
        price_exec = result_open.get("_meta", {}).get("price_executed") or float(price)
        update_entry("LONG", price_exec, qty)

    return {"status": "ok", "action": "GIRO_LONG", "close": result_close, "open": result_open}


def _giro_short(symbol: str, price: str, robot: str, payload: dict) -> dict:
    logger.info(f"🔄 GIRO_SHORT {symbol} [{robot}]")

    result_close = close_all_positions(symbol, "LONG", robot=robot)
    time.sleep(GIRO_BUFFER_SECONDS)

    qty = _calculate_qty(price, robot)
    if qty <= 0:
        return {"status": "error", "reason": "qty_calculation_failed"}

    result_open = place_order(symbol, "SELL", qty, "SHORT", price_signal=float(price), robot=robot)

    log_trade(signal="GIRO_SHORT_CLOSE", symbol=symbol, qty=0, price=price,
              result=result_close, robot=robot, demo=SIMULATION_MODE)
    log_trade(signal="GIRO_SHORT_OPEN", symbol=symbol, qty=qty, price=price,
              result=result_open, robot=robot, demo=SIMULATION_MODE)

    update_state({"last_signal": "GIRO_SHORT", "symbol": symbol})
    update_position(symbol, has_long=False, has_short=True)

    if result_open.get("code") == 0:
        price_exec = result_open.get("_meta", {}).get("price_executed") or float(price)
        update_entry("SHORT", price_exec, qty)

    return {"status": "ok", "action": "GIRO_SHORT", "close": result_close, "open": result_open}


# ============================================================
# 🛑 STOP LOSS — qty leída de posición real en BingX
# ============================================================

def _sl_long(symbol: str, signal: str, price: str, robot: str, payload: dict) -> dict:
    logger.info(f"🛑 {signal} {symbol} [{robot}]")
    result = close_all_positions(symbol, "LONG", robot=robot)
    log_trade(signal=signal, symbol=symbol, qty=0, price=price,
              result=result, robot=robot, demo=SIMULATION_MODE)
    update_state({"last_signal": signal, "symbol": symbol})
    update_position(symbol, has_long=False, has_short=False)
    return {"status": "ok", "action": signal, "result": result}


def _sl_short(symbol: str, signal: str, price: str, robot: str, payload: dict) -> dict:
    logger.info(f"🛑 {signal} {symbol} [{robot}]")
    result = close_all_positions(symbol, "SHORT", robot=robot)
    log_trade(signal=signal, symbol=symbol, qty=0, price=price,
              result=result, robot=robot, demo=SIMULATION_MODE)
    update_state({"last_signal": signal, "symbol": symbol})
    update_position(symbol, has_long=False, has_short=False)
    return {"status": "ok", "action": signal, "result": result}
