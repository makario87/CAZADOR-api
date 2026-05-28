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
from data.state import get_state, update_position, record_reconciler, get_our_order_ids, get_all_positions
from config.settings import RECONCILE_INTERVAL, SIMULATION_MODE
from logs.logger import get_logger
from core.signal_handler import _giro_in_progress

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
    if any(_giro_in_progress.values()):
    
            logger.info(
                "⏸️ Reconciler pausado — GIRO en progreso"
            )
    
            return        
    record_reconciler()

    bingx_data = get_positions()

    if not bingx_data:
        logger.warning("⚠️ Reconciliador sin respuesta BingX")
        return

    if bingx_data.get("code") != 0:
        logger.warning(f"⚠️ Reconciliador no pudo consultar BingX: {bingx_data}")
        return

    positions = bingx_data.get("data") or []

    # — Construir mapa BingX: symbol → {long, short} —
    bingx_map = {}
    for p in positions:
        amt  = float(p.get("positionAmt", 0))
        if amt == 0:
            continue
        sym  = p.get("symbol", "")
        side = p.get("positionSide", "")
        if sym not in bingx_map:
            bingx_map[sym] = {"long": False, "short": False}
        if side == "LONG":
            bingx_map[sym]["long"]  = True
        elif side == "SHORT":
            bingx_map[sym]["short"] = True

    # — Construir mapa Python: symbol → {long, short} —
    # Usa get_all_positions() — solo símbolos con posición abierta
    from brokers.bingx import normalize_symbol
    python_positions = get_all_positions()
    python_map = {
        normalize_symbol(sym): {"long": pos.get("long", False), "short": pos.get("short", False), "raw_symbol": sym}
        for sym, pos in python_positions.items()
    }

    # — Símbolos a verificar: unión de ambos mapas —
    all_symbols = set(bingx_map.keys()) | set(python_map.keys())

    if not all_symbols:
        logger.info("✅ Sin posiciones abiertas — estado sincronizado")
        _check_orphans(positions, python_map)
        return

    for sym in all_symbols:
        bingx_long  = bingx_map.get(sym, {}).get("long",  False)
        bingx_short = bingx_map.get(sym, {}).get("short", False)
        python_long  = python_map.get(sym, {}).get("long",  False)
        python_short = python_map.get(sym, {}).get("short", False)
        raw_symbol   = python_map.get(sym, {}).get("raw_symbol", sym)

        logger.info(
            f"🔍 [{sym}] Python(L={python_long} S={python_short}) vs "
            f"BingX(L={bingx_long} S={bingx_short})"
        )

        if python_long == bingx_long and python_short == bingx_short:
            logger.info(f"✅ [{sym}] Sincronizado")
            continue

        if bingx_long and not python_long:
            logger.warning(f"⚠️ [{sym}] DESYNC: BingX tiene LONG pero Python no → huérfana")
            _handle_orphan("LONG", raw_symbol)
            continue

        if bingx_short and not python_short:
            logger.warning(f"⚠️ [{sym}] DESYNC: BingX tiene SHORT pero Python no → huérfana")
            _handle_orphan("SHORT", raw_symbol)
            continue

        if python_long and not bingx_long:
            logger.error(f"🚨 [{sym}] DESYNC CRÍTICO: Python cree LONG pero BingX no tiene nada")
            _handle_missing_position("LONG", raw_symbol)
            continue

        if python_short and not bingx_short:
            logger.error(f"🚨 [{sym}] DESYNC CRÍTICO: Python cree SHORT pero BingX no tiene nada")
            _handle_missing_position("SHORT", raw_symbol)
            continue

    _check_orphans(positions, python_map)


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
            f"🖐️ CIERRE EXTERNO DETECTADO — {side} {symbol} "
            f"clientId={their_client_id} NO está en our_client_order_ids"
        )
        update_position(symbol, has_long=False, has_short=False)
        _set_external_close_flag(symbol, side, their_client_id)
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


def _check_orphans(positions: list, python_map: dict):
    """
    Verifica si hay posiciones en BingX para símbolos que Python
    no gestiona en absoluto. Solo loguea — no actúa.
    python_map: {bingx_symbol: {long, short, raw_symbol}}
    """
    from brokers.bingx import normalize_symbol

    for p in positions:
        amt = float(p.get("positionAmt", 0))
        if amt == 0:
            continue
        bingx_symbol = p.get("symbol", "")
        bingx_side   = p.get("positionSide", "")

        # Si Python gestiona este símbolo → ya lo verifica _check_state
        if bingx_symbol in python_map:
            continue

        logger.warning(
            f"👻 HUÉRFANA en símbolo no gestionado — "
            f"{bingx_side} {bingx_symbol} amt={amt}"
        )


# ============================================================
# 🚩 FLAGS — state.py (external_close_detected / external_activity_detected)
# ============================================================
def _set_external_close_flag(symbol: str, side: str, client_order_id: str):
    """
    Marca external_close_detected en state para que panel y Telegram lo lean.
    La lógica de detección vive aquí en el core — panel solo visualiza.
    """
    try:
        from data.state import set_flag
        set_flag("external_close_detected", True)
        logger.info(
            f"🚩 Flag external_close_detected=True — {side} {symbol} "
            f"clientId={client_order_id}"
        )
    except Exception as e:
        logger.error(f"❌ No se pudo marcar external_close_detected: {e}")


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
