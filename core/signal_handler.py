"""
core/signal_handler.py
Interpreta las señales de CAZADOR y las ejecuta en el broker.
TradingView manda solo la señal. Python calcula la qty.
"""
import time
from brokers.bingx import (
    place_order,
    place_stop_order,
    close_all_positions,
    get_balance
)
from data.state import (
    get_state,
    update_state,
    update_position,
    update_entry,
    increment_pyramid,
    update_bar_time,
    get_bar_time
)
from core.emergency import trigger_emergency
from config.settings import (
    GIRO_BUFFER_SECONDS,
    SIMULATION_MODE,
    RISK_PCT,
    PYRAMID_MAX_DEFAULT
)
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

def _calculate_qty(symbol: str, price_str: str, robot: str = "") -> float:
    """
    Calcula qty en contratos usando balance real de BingX.

    Fórmula:
        margen = balance_disponible × RISK_PCT
        qty    = margen / precio_actual

    Redondeo: usa round_qty() de market_info — stepSize real por símbolo.
    Validación min_qty: rechaza si qty < mínimo real del contrato.
    BingX aplica el leverage configurado manualmente en el broker.
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

        from brokers.market_info import round_qty, get_min_qty
        from brokers.bingx import normalize_symbol

        sym_normalized = normalize_symbol(symbol)
        margen         = available * RISK_PCT
        qty            = margen / price
        qty_rounded    = round_qty(sym_normalized, qty)
        min_qty        = get_min_qty(sym_normalized)

        if min_qty > 0 and qty_rounded < min_qty:
            logger.warning(
                f"⚠️ [{robot}] qty={qty_rounded} < min_qty={min_qty} "
                f"para {sym_normalized} — orden rechazada"
            )
            return 0.0

        logger.info(
            f"💰 [{robot}] Sizing {sym_normalized}: "
            f"balance={available:.2f} USDT × {RISK_PCT*100:.3f}% "
            f"= {margen:.4f} USDT / price={price} "
            f"= {qty:.6f} → round={qty_rounded} (min={min_qty})"
        )
        return float(qty_rounded)

    except Exception as e:
        logger.error(f"❌ [{robot}] Error calculando qty: {e}")
        return 0.0

# ============================================================
# 🛡️ SL BROKER — red de seguridad BingX
# ============================================================

def _send_sl_broker(
    symbol: str,
    position_side: str,
    qty: float,
    sl_promedio_str: str,
    sl_last_str: str,
    robot: str
) -> None:
    """
    Calcula y coloca STOP_MARKET en BingX como red de seguridad.

    IMPORTANTE:
    - SOLO se ejecuta tras entrada confirmada OK.
    - NO activa emergencia si falla.
    - TradingView sigue siendo la fuente de verdad.
    """

    try:

        sl_promedio = float(sl_promedio_str or 0)
        sl_last     = float(sl_last_str or 0)

        # Ningún SL disponible
        if sl_promedio <= 0 and sl_last <= 0:

            logger.info(
                f"ℹ️ [{robot}] SL broker omitido — "
                f"sl_promedio=0 y sl_last=0"
            )

            return

        # Solo candidatos válidos
        candidates = [v for v in [sl_promedio, sl_last] if v > 0]

        if not candidates:

            logger.info(
                f"ℹ️ [{robot}] SL broker omitido — sin candidatos válidos"
            )

            return

        # LONG → coger el más cercano por abajo
        if position_side == "LONG":

            sl_raw = min(candidates)

            # pequeño margen para evitar trigger prematuro
            sl_broker = round(sl_raw * 0.99, 8)

            close_side = "SELL"

        # SHORT → coger el más cercano por arriba
        else:

            sl_raw = max(candidates)

            sl_broker = round(sl_raw * 1.01, 8)

            close_side = "BUY"

        logger.info(
            f"🛡️ [{robot}] SL broker {position_side} {symbol} — "
            f"sl_promedio={sl_promedio} "
            f"sl_last={sl_last} "
            f"→ sl_raw={sl_raw} "
            f"→ sl_broker={sl_broker}"
        )

        result = place_stop_order(
            symbol=symbol,
            side=close_side,
            position_side=position_side,
            stop_price=sl_broker,
            quantity=qty,
            robot=robot
        )

        if result.get("code") != 0:

            logger.warning(
                f"⚠️ [{robot}] SL broker no colocado — "
                f"code={result.get('code')} "
                f"msg={result.get('msg')} "
                f"— TV seguirá gestionando SL"
            )

    except Exception as e:

        logger.error(
            f"❌ [{robot}] Excepción en _send_sl_broker: {e}"
        )
        
# ============================================================
# 🚀 DISPATCHER PRINCIPAL
# ============================================================

# Señales que NUNCA se bloquean aunque haya emergencia
PROTECTION_SIGNALS = {
    "CLOSE_LONG", "CLOSE_SHORT",
    "GIRO_LONG", "GIRO_SHORT",
    "SL_LONG_DYNAMIC", "SL_SHORT_DYNAMIC",
    "SL_LONG_BLACK", "SL_SHORT_BLACK",
    "SL_LONG_CCI", "SL_SHORT_CCI",
    "SL_LONG_PROMEDIO", "SL_SHORT_PROMEDIO",
    "SL_LONG_LAST", "SL_SHORT_LAST",
}

def handle_signal(payload: dict) -> dict:
    signal = payload.get("signal", "").upper()
    symbol = payload.get("symbol", "")
    price  = payload.get("price", "0")
    robot  = payload.get("robot", "CAZADOR")

    logger.info(f"📨 Señal recibida: {signal} | {symbol} | price={price} | robot={robot}")

    if signal not in VALID_SIGNALS:
        logger.warning(f"⚠️ Señal desconocida ignorada: {signal}")
        return {"status": "ignored", "reason": "unknown_signal"}

    # ============================================================
    # 📈 CONTROL PIRÁMIDE + 🔒 ANTI-DUPLICADOS
    # ============================================================
    if signal in ("ENTRY_LONG", "ENTRY_SHORT"):
        pyramid_current = int(payload.get("pyramid_current", 0))
        pyramid_max     = int(payload.get("pyramid_max", PYRAMID_MAX_DEFAULT))

        if pyramid_current > pyramid_max:
            logger.warning(
                f"⛔ {signal} rechazada — pirámide llena: "
                f"{pyramid_current}/{pyramid_max} [{robot}]"
            )
            return {
                "status":  "rejected",
                "reason":  "pyramid_full",
                "current": pyramid_current,
                "max":     pyramid_max
            }

        signal_time = payload.get("time", "")
        signal_tf   = payload.get("tf", "")
        
        last_bar_time, last_bar_tf = get_bar_time(symbol)
        
        if (signal_time and signal_time == last_bar_time
                and signal_tf == last_bar_tf):
                    
            logger.warning(
                f"⛔ {signal} rechazada — ya hubo entrada en esta vela "
                f"[time={signal_time} tf={signal_tf}] [{robot}]"
            )
            return {
                "status": "rejected",
                "reason": "duplicate_entry_same_bar",
                "time":   signal_time,
                "tf":     signal_tf
            }

    # ============================================================
    # 🚨 CONTROL EMERGENCIA
    # ============================================================
    state = get_state()
    if state.get("emergency"):
        if signal in PROTECTION_SIGNALS:
            logger.warning(f"⚠️ EMERGENCIA ACTIVA pero señal de protección — ejecutando igualmente: {signal}")
        else:
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
    qty = _calculate_qty(symbol, price, robot)

    if qty <= 0:
        return {"status": "error", "reason": "qty_calculation_failed"}

    logger.info(f"🟢 ENTRY_LONG {symbol} qty={qty} price={price} [{robot}]")

    result = place_order(
        symbol,
        "BUY",
        qty,
        "LONG",
        price_signal=float(price),
        robot=robot
    )

    log_trade(
        signal="ENTRY_LONG",
        symbol=symbol,
        qty=qty,
        price=price,
        result=result,
        robot=robot,
        demo=SIMULATION_MODE
    )

    code = result.get("code", -1)

    if code == 0:
        update_state({"last_signal": "ENTRY_LONG", "symbol": symbol})
        update_position(symbol, has_long=True, has_short=False)

        price_exec = result.get("_meta", {}).get("price_executed") or float(price)

        update_entry(symbol, "LONG", price_exec, qty)
        increment_pyramid(symbol, "LONG")
        update_bar_time(symbol, payload.get("time", ""), payload.get("tf", ""))
        # 🛡️ SL BROKER
        _send_sl_broker(
            symbol,
            "LONG",
            qty,
            payload.get("sl_promedio", "0"),
            payload.get("sl_last", "0"),
            robot
        )

        logger.info(f"✅ ENTRY_LONG ejecutado y state actualizado [{robot}]")

    else:
        logger.error(
            f"❌ ENTRY_LONG FALLÓ — state NO actualizado. "
            f"code={code} msg={result.get('msg')} [{robot}]"
        )

    return {
        "status": "ok" if code == 0 else "error",
        "action": "ENTRY_LONG",
        "qty": qty,
        "result": result
    }


def _entry_short(symbol: str, price: str, robot: str, payload: dict) -> dict:
    qty = _calculate_qty(symbol, price, robot)

    if qty <= 0:
        return {"status": "error", "reason": "qty_calculation_failed"}

    logger.info(f"🔴 ENTRY_SHORT {symbol} qty={qty} price={price} [{robot}]")

    result = place_order(
        symbol,
        "SELL",
        qty,
        "SHORT",
        price_signal=float(price),
        robot=robot
    )

    log_trade(
        signal="ENTRY_SHORT",
        symbol=symbol,
        qty=qty,
        price=price,
        result=result,
        robot=robot,
        demo=SIMULATION_MODE
    )

    code = result.get("code", -1)

    if code == 0:
        update_state({"last_signal": "ENTRY_SHORT", "symbol": symbol})
        update_position(symbol, has_long=False, has_short=True)

        price_exec = result.get("_meta", {}).get("price_executed") or float(price)

        update_entry(symbol, "SHORT", price_exec, qty)
        increment_pyramid(symbol, "SHORT")
        update_bar_time(symbol, payload.get("time", ""), payload.get("tf", ""))
        # 🛡️ SL BROKER
        _send_sl_broker(
            symbol,
            "SHORT",
            qty,
            payload.get("sl_promedio", "0"),
            payload.get("sl_last", "0"),
            robot
        )
        
        logger.info(f"✅ ENTRY_SHORT ejecutado y state actualizado [{robot}]")

    else:
        logger.error(
            f"❌ ENTRY_SHORT FALLÓ — state NO actualizado. "
            f"code={code} msg={result.get('msg')} [{robot}]"
        )

    return {
        "status": "ok" if code == 0 else "error",
        "action": "ENTRY_SHORT",
        "qty": qty,
        "result": result
    }


# ============================================================
# 📉 CIERRES — qty leída de posición real en BingX
# ============================================================

def _close_long(symbol: str, price: str, robot: str, payload: dict) -> dict:
    logger.info(f"⬜ CLOSE_LONG {symbol} [{robot}]")
    result = close_all_positions(symbol, "LONG", robot=robot)
    log_trade(signal="CLOSE_LONG", symbol=symbol, qty=0, price=price,
              result=result, robot=robot, demo=SIMULATION_MODE)

    code = result.get("code", -1)
    if code == 0:
        update_state({"last_signal": "CLOSE_LONG", "symbol": symbol})
        update_position(symbol, has_long=False, has_short=False)
        logger.info(f"✅ CLOSE_LONG ejecutado y state actualizado [{robot}]")
    else:
        if result.get("msg") == "no_open_position":
            logger.info(f"ℹ️ CLOSE_LONG — no había LONG en BingX, actualizando state [{robot}]")
            update_state({"last_signal": "CLOSE_LONG", "symbol": symbol})
            update_position(symbol, has_long=False, has_short=False)
        else:
            logger.error(f"❌ CLOSE_LONG FALLÓ en BingX — state NO actualizado. code={code} msg={result.get('msg')} [{robot}]")
            trigger_emergency(f"CLOSE_LONG no ejecutó cierre en BingX: code={code} msg={result.get('msg')}")

    return {"status": "ok" if code == 0 else "error", "action": "CLOSE_LONG", "result": result}

def _close_short(symbol: str, price: str, robot: str, payload: dict) -> dict:
    logger.info(f"⬜ CLOSE_SHORT {symbol} [{robot}]")
    result = close_all_positions(symbol, "SHORT", robot=robot)
    log_trade(signal="CLOSE_SHORT", symbol=symbol, qty=0, price=price,
              result=result, robot=robot, demo=SIMULATION_MODE)

    code = result.get("code", -1)
    if code == 0:
        update_state({"last_signal": "CLOSE_SHORT", "symbol": symbol})
        update_position(symbol, has_long=False, has_short=False)
        logger.info(f"✅ CLOSE_SHORT ejecutado y state actualizado [{robot}]")
    else:
        if result.get("msg") == "no_open_position":
            logger.info(f"ℹ️ CLOSE_SHORT — no había SHORT en BingX, actualizando state [{robot}]")
            update_state({"last_signal": "CLOSE_SHORT", "symbol": symbol})
            update_position(symbol, has_long=False, has_short=False)
        else:
            logger.error(f"❌ CLOSE_SHORT FALLÓ en BingX — state NO actualizado. code={code} msg={result.get('msg')} [{robot}]")
            trigger_emergency(f"CLOSE_SHORT no ejecutó cierre en BingX: code={code} msg={result.get('msg')}")

    return {"status": "ok" if code == 0 else "error", "action": "CLOSE_SHORT", "result": result}


# ============================================================
# 🔄 GIROS
# ============================================================

def _giro_long(symbol, price, robot, payload):
    logger.info(f"🔄 GIRO_LONG {symbol} [{robot}]")

    result_close = close_all_positions(symbol, "SHORT", robot=robot)

    code_close = result_close.get("code", -1)

    if code_close != 0:
        if result_close.get("msg") == "no_open_position":
            logger.info(f"ℹ️ GIRO_LONG — no había SHORT en BingX, abriendo LONG directamente [{robot}]")
        else:
            logger.error(f"❌ GIRO_LONG cierre SHORT falló — abortando. code={code_close} [{robot}]")
            trigger_emergency(f"GIRO_LONG no cerró SHORT: code={code_close} msg={result_close.get('msg')}")
            log_trade(signal="GIRO_LONG_CLOSE", symbol=symbol, qty=0, price=price, result=result_close, robot=robot, demo=SIMULATION_MODE)
            return {"status": "error", "action": "GIRO_LONG", "reason": "close_failed", "close": result_close}

    time.sleep(GIRO_BUFFER_SECONDS)

    qty = _calculate_qty(symbol, price, robot)

    if qty <= 0:
        return {"status": "error", "reason": "qty_calculation_failed"}

    result_open = place_order(
        symbol,
        "BUY",
        qty,
        "LONG",
        price_signal=float(price),
        robot=robot
    )

    log_trade(
        signal="GIRO_LONG_CLOSE",
        symbol=symbol,
        qty=0,
        price=price,
        result=result_close,
        robot=robot,
        demo=SIMULATION_MODE
    )

    log_trade(
        signal="GIRO_LONG_OPEN",
        symbol=symbol,
        qty=qty,
        price=price,
        result=result_open,
        robot=robot,
        demo=SIMULATION_MODE
    )

    code_open = result_open.get("code", -1)

    if code_open == 0:
        update_state({"last_signal": "GIRO_LONG", "symbol": symbol})

        update_position(
            symbol,
            has_long=True,
            has_short=False
        )

        price_exec = (
            result_open.get("_meta", {}).get("price_executed")
            or float(price)
        )

        update_entry(symbol, "LONG", price_exec, qty)
        increment_pyramid(symbol, "LONG")
        update_bar_time(symbol, payload.get("time", ""), payload.get("tf", ""))
        # 🛡️ SL BROKER
        _send_sl_broker(
            symbol,
            "LONG",
            qty,
            payload.get("sl_promedio", "0"),
            payload.get("sl_last", "0"),
            robot
        )

        logger.info(f"✅ GIRO_LONG completo [{robot}]")

    else:
        logger.error(
            f"❌ GIRO_LONG apertura LONG falló — "
            f"SHORT cerrado pero LONG no abierto. "
            f"code={code_open} [{robot}]"
        )

        trigger_emergency(
            f"GIRO_LONG cerró SHORT pero no abrió LONG: "
            f"code={code_open} "
            f"msg={result_open.get('msg')}"
        )

    return {
        "status": "ok" if code_open == 0 else "error",
        "action": "GIRO_LONG",
        "close": result_close,
        "open": result_open
    }

def _giro_short(symbol, price, robot, payload):
    logger.info(f"🔄 GIRO_SHORT {symbol} [{robot}]")

    result_close = close_all_positions(symbol, "LONG", robot=robot)

    code_close = result_close.get("code", -1)

    if code_close != 0:
        if result_close.get("msg") == "no_open_position":
            logger.info(f"ℹ️ GIRO_SHORT — no había LONG en BingX, abriendo SHORT directamente [{robot}]")
        else:
            logger.error(f"❌ GIRO_SHORT cierre LONG falló — abortando. code={code_close} [{robot}]")
            trigger_emergency(f"GIRO_SHORT no cerró LONG: code={code_close} msg={result_close.get('msg')}")
            log_trade(signal="GIRO_SHORT_CLOSE", symbol=symbol, qty=0, price=price, result=result_close, robot=robot, demo=SIMULATION_MODE)
            return {"status": "error", "action": "GIRO_SHORT", "reason": "close_failed", "close": result_close}

    time.sleep(GIRO_BUFFER_SECONDS)

    qty = _calculate_qty(symbol, price, robot)

    if qty <= 0:
        return {"status": "error", "reason": "qty_calculation_failed"}

    result_open = place_order(
        symbol,
        "SELL",
        qty,
        "SHORT",
        price_signal=float(price),
        robot=robot
    )

    log_trade(
        signal="GIRO_SHORT_CLOSE",
        symbol=symbol,
        qty=0,
        price=price,
        result=result_close,
        robot=robot,
        demo=SIMULATION_MODE
    )

    log_trade(
        signal="GIRO_SHORT_OPEN",
        symbol=symbol,
        qty=qty,
        price=price,
        result=result_open,
        robot=robot,
        demo=SIMULATION_MODE
    )

    code_open = result_open.get("code", -1)

    if code_open == 0:
        update_state({"last_signal": "GIRO_SHORT", "symbol": symbol})

        update_position(
            symbol,
            has_long=False,
            has_short=True
        )

        price_exec = (
            result_open.get("_meta", {}).get("price_executed")
            or float(price)
        )

        update_entry(symbol, "SHORT", price_exec, qty)
        increment_pyramid(symbol, "SHORT")
        update_bar_time(symbol, payload.get("time", ""), payload.get("tf", ""))
        # 🛡️ SL BROKER
        _send_sl_broker(
            symbol,
            "SHORT",
            qty,
            payload.get("sl_promedio", "0"),
            payload.get("sl_last", "0"),
            robot
        )

        logger.info(f"✅ GIRO_SHORT completo [{robot}]")

    else:
        logger.error(
            f"❌ GIRO_SHORT apertura SHORT falló — "
            f"LONG cerrado pero SHORT no abierto. "
            f"code={code_open} [{robot}]"
        )

        trigger_emergency(
            f"GIRO_SHORT cerró LONG pero no abrió SHORT: "
            f"code={code_open} "
            f"msg={result_open.get('msg')}"
        )

    return {
        "status": "ok" if code_open == 0 else "error",
        "action": "GIRO_SHORT",
        "close": result_close,
        "open": result_open
    }


# ============================================================
# 🛑 STOP LOSS — qty leída de posición real en BingX
# ============================================================

def _sl_long(symbol: str, signal: str, price: str, robot: str, payload: dict) -> dict:
    logger.info(f"🛑 {signal} {symbol} [{robot}]")
    result = close_all_positions(symbol, "LONG", robot=robot)
    
    log_trade(signal=signal, symbol=symbol, qty=0, price=price,
              result=result, robot=robot, demo=SIMULATION_MODE)
    
    code = result.get("code", -1)
    if code == 0:
        update_state({"last_signal": signal, "symbol": symbol})
        update_position(symbol, has_long=False, has_short=False)
        logger.info(f"✅ {signal} ejecutado y state actualizado [{robot}]")
    else:
        if result.get("msg") == "no_open_position":
            logger.info(f"ℹ️ {signal} — no había LONG en BingX, actualizando state [{robot}]")
            update_state({"last_signal": signal, "symbol": symbol})
            update_position(symbol, has_long=False, has_short=False)
        else:
            logger.error(f"❌ {signal} FALLÓ en BingX — state NO actualizado. code={code} msg={result.get('msg')} [{robot}]")
            trigger_emergency(f"{signal} no ejecutó cierre en BingX: code={code} msg={result.get('msg')}")
    
    return {"status": "ok" if code == 0 else "error", "action": signal, "result": result}


def _sl_short(symbol: str, signal: str, price: str, robot: str, payload: dict) -> dict:
    logger.info(f"🛑 {signal} {symbol} [{robot}]")
    result = close_all_positions(symbol, "SHORT", robot=robot)
    
    log_trade(signal=signal, symbol=symbol, qty=0, price=price,
              result=result, robot=robot, demo=SIMULATION_MODE)
    
    code = result.get("code", -1)
    if code == 0:
        update_state({"last_signal": signal, "symbol": symbol})
        update_position(symbol, has_long=False, has_short=False)
        logger.info(f"✅ {signal} ejecutado y state actualizado [{robot}]")
    else:
        if result.get("msg") == "no_open_position":
            logger.info(f"ℹ️ {signal} — no había SHORT en BingX, actualizando state [{robot}]")
            update_state({"last_signal": signal, "symbol": symbol})
            update_position(symbol, has_long=False, has_short=False)
        else:
            logger.error(f"❌ {signal} FALLÓ en BingX — state NO actualizado. code={code} msg={result.get('msg')} [{robot}]")
            trigger_emergency(f"{signal} no ejecutó cierre en BingX: code={code} msg={result.get('msg')}")
    
    return {"status": "ok" if code == 0 else "error", "action": signal, "result": result}
