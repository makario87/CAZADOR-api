"""
core/reconciler.py
Reconciliador real: compara estado Python vs estado BingX.

FASE ACTUAL:  compara si hay posición o no + dirección LONG/SHORT
              + detección cierre manual (#3)
              + detección posiciones huérfanas (#4)
FASE FUTURA:  qty exacta, precio entrada, pnl
"""
import threading
import time

from brokers.bingx import get_positions, get_balance, get_order_history
from core.emergency import trigger_emergency
from data.state import get_state, update_position, record_reconciler, get_our_order_ids
from config.settings import RECONCILE_INTERVAL, SIMULATION_MODE
from logs.logger import get_logger

logger = get_logger(__name__)

_reconciler_thread = None


# ============================================================
# 🚀 ARRANQUE
# ============================================================
def start_reconciler():
    global _reconciler_thread
    if _reconciler_thread and _reconciler_thread.is_alive():
        return
    _reconciler_thread = threading.Thread(target=_reconcile_loop, daemon=True)
    _reconciler_thread.start()
    logger.info(f"🔄 Reconciliador arrancado (cada {RECONCILE_INTERVAL}s)")


def is_alive() -> bool:
    return _reconciler_thread is not None and _reconciler_thread.is_alive()


# ============================================================
# 🔄 LOOP
# ============================================================
_is_running = False

def _reconcile_loop():
    global _is_running
    if _is_running:
        logger.warning("⚠️ Reconciliador ya corriendo — ignorando segunda instancia")
        return
    _is_running = True
    while True:
        try:
            time.sleep(RECONCILE_INTERVAL)
            _check_state()
        except Exception as e:
            logger.error(f"❌ Error en reconciliador: {e}")


# ============================================================
# 🔍 CHECK REAL
# ============================================================
def _check_state():
    record_reconciler()

    bingx_data = get_positions()

    if not bingx_data:
        logger.warning("⚠️ Reconciliador sin respuesta BingX")
        return

    if bingx_data.get("code") != 0:
        logger.warning(f"⚠️ Reconciliador no pudo consultar BingX: {bingx_data}")
        return

    positions = bingx_data.get("data") or []

    bingx_long = any(
        p.get("positionSide") == "LONG" and float(p.get("positionAmt", 0)) != 0
        for p in positions
    )
    bingx_short = any(
        p.get("positionSide") == "SHORT" and float(p.get("positionAmt", 0)) != 0
        for p in positions
    )

    state        = get_state()
    python_long  = state.get("position_long",  False)
    python_short = state.get("position_short", False)
    symbol       = state.get("position_symbol", "?")

    logger.info(
        f"🔍 Reconciliación: "
        f"Python(L={python_long} S={python_short}) vs "
        f"BingX(L={bingx_long} S={bingx_short})"
    )

    # ── SINCRONIZADO ─────────────────────────────────────────
    if python_long == bingx_long and python_short == bingx_short:
        logger.info("✅ Estado sincronizado correctamente")
        _check_orphans(positions, symbol)
        return

    # ── DESYNC: BingX tiene algo que Python no sabe ──────────
    # → Posición huérfana (abierta externamente)
    if bingx_long and not python_long:
        logger.warning("⚠️ DESYNC: BingX tiene LONG pero Python no lo sabe → posición huérfana")
        _handle_orphan("LONG", symbol)
        return

    if bingx_short and not python_short:
        logger.warning("⚠️ DESYNC: BingX tiene SHORT pero Python no lo sabe → posición huérfana")
        _handle_orphan("SHORT", symbol)
        return

    # ── DESYNC CRÍTICO: Python cree que hay posición pero BingX no tiene nada ──
    # → Puede ser cierre manual o error real
    if python_long and not bingx_long:
        logger.error("🚨 DESYNC CRÍTICO: Python cree LONG pero BingX no tiene nada")
        _handle_missing_position("LONG", symbol)
        return

    if python_short and not bingx_short:
        logger.error("🚨 DESYNC CRÍTICO: Python cree SHORT pero BingX no tiene nada")
        _handle_missing_position("SHORT", symbol)
        return


# ============================================================
# 🔍 #3 — DETECCIÓN CIERRE MANUAL
# ============================================================
def _handle_missing_position(side: str, symbol: str):
    """
    Python cree que hay posición pero BingX no tiene nada.

    Flujo:
      1. Consulta historial de órdenes BingX para el símbolo
      2. Busca la orden de cierre más reciente (SELL para LONG, BUY para SHORT)
      3. ¿clientOrderID está en our_client_order_ids?
         → SÍ: ya lo procesamos nosotros (CLOSE/SL/GIRO) → limpia state → OK
         → NO: cierre externo detectado (manual u otro sistema) → limpia state + log + flags
         → Sin historial: caso grave → emergencia
    """
    if symbol == "?":
        logger.error("🚨 _handle_missing_position — symbol desconocido → emergencia")
        if not SIMULATION_MODE:
            trigger_emergency(f"DESYNC CRÍTICO {side} — symbol desconocido")
        return

    logger.info(f"🔎 Consultando historial órdenes {symbol} para determinar causa del desync...")
    history = get_order_history(symbol, limit=20)

    if not history:
        # Sin historial → no podemos determinar causa → emergencia
        logger.error(
            f"🚨 DESYNC CRÍTICO {side} {symbol} — sin historial de órdenes → emergencia"
        )
        update_position(symbol, has_long=False, has_short=False)
        if not SIMULATION_MODE:
            trigger_emergency(f"DESYNC CRÍTICO {side} — sin historial")
        return

    # Buscar la orden de cierre más reciente para este side
    close_side_filter = "SELL" if side == "LONG" else "BUY"

    close_order = next(
        (
            o for o in history
            if o.get("positionSide") == side
            and o.get("side") == close_side_filter
            and o.get("status") == "FILLED"
        ),
        None
    )

    if not close_order:
        # Hay historial pero no encontramos orden de cierre → raro → emergencia
        logger.error(
            f"🚨 DESYNC CRÍTICO {side} {symbol} — historial sin orden de cierre → emergencia"
        )
        update_position(symbol, has_long=False, has_short=False)
        if not SIMULATION_MODE:
            trigger_emergency(f"DESYNC CRÍTICO {side} — sin orden cierre en historial")
        return

    their_client_id = close_order.get("clientOrderId", "")
    our_ids         = get_our_order_ids()

    if their_client_id in our_ids:
        # La cerró nuestro sistema (CLOSE/SL/GIRO) — state desactualizado por algún motivo
        logger.warning(
            f"⚠️ DESYNC {side} {symbol} — cerrado por nuestro sistema "
            f"(clientId={their_client_id}) — limpiando state"
        )
        update_position(symbol, has_long=False, has_short=False)
        # No es emergencia — autorregulación normal
    else:
        # ClientOrderID no es nuestro → cierre externo (manual u otro sistema)
        logger.warning(
            f"🖐️ CIERRE MANUAL DETECTADO — {side} {symbol} "
            f"clientId={their_client_id} NO está en our_client_order_ids"
        )
        update_position(symbol, has_long=False, has_short=False)
        _set_manual_close_flag(symbol, side, their_client_id)
        # Robot sigue activo — se autorregula con siguiente señal TV
        logger.info(
            f"✅ State limpiado — robot sigue activo — "
            f"esperando siguiente señal TV para {symbol}"
        )


# ============================================================
# 🔍 #4 — DETECCIÓN POSICIONES HUÉRFANAS
# ============================================================
def _handle_orphan(side: str, symbol: str):
    """
    BingX tiene posición que Python no abrió → huérfana.
    No cerramos automáticamente — esperamos SL natural de TV.
    Solo logueamos y marcamos flag.
    """
    logger.warning(
        f"👻 POSICIÓN HUÉRFANA detectada — {side} {symbol} "
        f"(BingX tiene posición que Python no registró)"
    )
    _set_external_activity_flag(symbol, side)
    # NO trigger_emergency — NO cerrar — TV gobernará con su SL natural
    logger.info(
        f"ℹ️ Huérfana {side} {symbol} — no se cierra automáticamente — "
        f"TV gobernará con SL natural"
    )


def _check_orphans(positions: list, our_symbol: str):
    """
    Cuando estado está sincronizado, verificar si hay posiciones
    en BingX para símbolos que Python no gestiona en absoluto.
    Solo loguea — no actúa.
    """
    state = get_state()
    from brokers.bingx import normalize_symbol

    our_symbol_bingx = normalize_symbol(
        state.get("position_symbol") or ""
    )

    for p in positions:
        amt = float(p.get("positionAmt", 0))
        if amt == 0:
            continue
        bingx_symbol = p.get("symbol", "")
        bingx_side   = p.get("positionSide", "")

        # Si es nuestro símbolo activo, ya lo gestiona _check_state → ignorar
        if bingx_symbol == our_symbol_bingx:
            continue

        logger.warning(
            f"👻 HUÉRFANA en símbolo no gestionado — "
            f"{bingx_side} {bingx_symbol} amt={amt}"
        )


# ============================================================
# 🚩 FLAGS — state.py (manual_close_detected / external_activity_detected)
# ============================================================
def _set_manual_close_flag(symbol: str, side: str, client_order_id: str):
    """
    Marca manual_close_detected en state para que panel y Telegram lo lean.
    La lógica de detección vive aquí en el core — panel solo visualiza.
    """
    try:
        from data.state import set_flag
        set_flag("manual_close_detected", True)
        logger.info(
            f"🚩 Flag manual_close_detected=True — {side} {symbol} "
            f"clientId={client_order_id}"
        )
    except Exception as e:
        logger.error(f"❌ No se pudo marcar manual_close_detected: {e}")


def _set_external_activity_flag(symbol: str, side: str):
    """
    Marca external_activity_detected en state para huérfanas y actividad externa.
    """
    try:
        from data.state import set_flag
        set_flag("external_activity_detected", True)
        logger.info(
            f"🚩 Flag external_activity_detected=True — {side} {symbol}"
        )
    except Exception as e:
        logger.error(f"❌ No se pudo marcar external_activity_detected: {e}")


# ============================================================
# 🧪 RECONCILIACIÓN MANUAL
# ============================================================
def reconcile_now(symbol: str = "") -> dict:
    record_reconciler()
    return {
        "balance":   get_balance(),
        "positions": get_positions(symbol),
    }
