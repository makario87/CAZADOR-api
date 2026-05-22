"""
data/state.py
Estado global del sistema en memoria.
BingX es siempre la fuente de verdad para posiciones reales.
Este estado es auxiliar para control interno.
"""
import threading
from logs.logger import get_logger

logger = get_logger(__name__)

_lock  = threading.Lock()
_state = {
    "emergency":   False,
    "last_signal": None,
    "symbol":      None,
    "blocked":     False,
}

def get_state() -> dict:
    with _lock:
        return _state.copy()

def update_state(updates: dict):
    with _lock:
        _state.update(updates)
        logger.info(f"📊 Estado actualizado: {updates}")

def reset_state():
    with _lock:
        _state.update({
            "emergency":   False,
            "last_signal": None,
            "symbol":      None,
            "blocked":     False,
        })
    logger.info("🔄 Estado reseteado")
