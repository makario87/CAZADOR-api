"""
core/reconciler.py
Reconciliador real: compara estado Python vs estado BingX.
 
FASE ACTUAL:  compara si hay posición o no + dirección LONG/SHORT
FASE FUTURA:  qty exacta, precio entrada, pnl
"""
import threading
import time
 
from brokers.bingx import get_positions, get_balance
from core.emergency import trigger_emergency
from data.state import get_state, update_position, record_reconciler
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
    time.sleep(2)
    record_reconciler()
 
    bingx_data = get_positions()
 
    if not bingx_data:
        logger.warning("⚠️ Reconciliador sin respuesta BingX")
        return
 
    if bingx_data.get("code") != 0:
        logger.warning(f"⚠️ Reconciliador no pudo consultar BingX: {bingx_data}")
        return
 
    positions = bingx_data.get("data") or []  # data es lista directa en BingX API
 
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
 
    if python_long == bingx_long and python_short == bingx_short:
        logger.info("✅ Estado sincronizado correctamente")
        return
 
    if bingx_long and not python_long:
        logger.warning("⚠️ DESYNC: BingX tiene LONG pero Python no lo sabe")
        update_position(symbol, has_long=True, has_short=False)
        if not SIMULATION_MODE:
            trigger_emergency("DESYNC: BingX tiene LONG no registrado")
        return
 
    if bingx_short and not python_short:
        logger.warning("⚠️ DESYNC: BingX tiene SHORT pero Python no lo sabe")
        update_position(symbol, has_long=False, has_short=True)
        if not SIMULATION_MODE:
            trigger_emergency("DESYNC: BingX tiene SHORT no registrado")
        return
 
    if python_long and not bingx_long:
        logger.error("🚨 DESYNC CRÍTICO: Python cree LONG pero BingX no tiene nada")
        update_position(symbol, has_long=False, has_short=False)
        if not SIMULATION_MODE:
            trigger_emergency("DESYNC CRÍTICO LONG")
        return
 
    if python_short and not bingx_short:
        logger.error("🚨 DESYNC CRÍTICO: Python cree SHORT pero BingX no tiene nada")
        update_position(symbol, has_long=False, has_short=False)
        if not SIMULATION_MODE:
            trigger_emergency("DESYNC CRÍTICO SHORT")
        return
 
# ============================================================
# 🧪 RECONCILIACIÓN MANUAL
# ============================================================
def reconcile_now(symbol: str = "") -> dict:
    record_reconciler()
    return {
        "balance":   get_balance(),
        "positions": get_positions(symbol),
    }
