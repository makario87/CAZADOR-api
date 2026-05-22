"""
core/reconciler.py
Verifica que el estado real de BingX coincide con lo que TradingView espera.
Si hay desync → activa emergencia.
TODO: comparar posiciones TV vs BingX en detalle.
"""
import threading
import time
from brokers.bingx import get_positions, get_balance
from core.emergency import trigger_emergency
from data.state import record_reconciler
from config.settings import RECONCILE_INTERVAL
from logs.logger import get_logger

logger = get_logger(__name__)

_reconciler_thread = None

def start_reconciler():
    """Arranca el reconciliador en background."""
    global _reconciler_thread
    if _reconciler_thread and _reconciler_thread.is_alive():
        return
    _reconciler_thread = threading.Thread(target=_reconcile_loop, daemon=True)
    _reconciler_thread.start()
    logger.info(f"🔄 Reconciliador arrancado (cada {RECONCILE_INTERVAL}s)")

def _reconcile_loop():
    """Loop que verifica el estado cada X segundos."""
    while True:
        try:
            time.sleep(RECONCILE_INTERVAL)
            _check_state()
        except Exception as e:
            logger.error(f"❌ Error en reconciliador: {e}")

def _check_state():
    """
    TODO: Implementar comparación completa TV vs BingX.
    Por ahora solo consulta y loguea el estado real del broker.
    """
    record_reconciler()
    logger.info("🔍 Reconciliación — consultando estado BingX...")
    balance   = get_balance()
    positions = get_positions()
    logger.info(f"💰 Balance: {balance}")
    logger.info(f"📋 Posiciones: {positions}")
    # TODO: comparar con estado esperado de TradingView
    # Si hay desync → trigger_emergency("Desync detectado")

def reconcile_now(symbol: str = "") -> dict:
    """Reconciliación manual desde el panel."""
    logger.info(f"🔍 Reconciliación manual: {symbol or 'todos'}")
    balance   = get_balance()
    positions = get_positions(symbol)
    return {"balance": balance, "positions": positions}

def is_alive() -> bool:
    return _reconciler_thread is not None and _reconciler_thread.is_alive()
