"""
data/state.py
"""
import threading
from utils.time_utils import format_log_time
from logs.logger import get_logger

logger = get_logger(__name__)

_lock  = threading.Lock()
_state = {
    "emergency":              False,
    "last_signal":            None,
    "symbol":                 None,
    "blocked":                False,
    "last_webhook_time":      None,
    "last_reconciler_time":   None,
    "last_webhook_signal":    None,
    "webhooks_received":      0,
    "webhooks_ok":            0,
    "webhooks_failed":        0,
}

def get_state() -> dict:
    with _lock:
        return _state.copy()

def update_state(updates: dict):
    with _lock:
        _state.update(updates)

def record_webhook(signal: str, ok: bool):
    with _lock:
        _state["last_webhook_time"]   = format_log_time()
        _state["last_webhook_signal"] = signal
        _state["webhooks_received"]  += 1
        if ok:
            _state["webhooks_ok"]    += 1
        else:
            _state["webhooks_failed"] += 1

def record_reconciler():
    with _lock:
        _state["last_reconciler_time"] = format_log_time()

def reset_state():
    with _lock:
        _state.update({
            "emergency":            False,
            "last_signal":          None,
            "symbol":               None,
            "blocked":              False,
            "last_webhook_time":    None,
            "last_reconciler_time": None,
            "last_webhook_signal":  None,
            "webhooks_received":    0,
            "webhooks_ok":          0,
            "webhooks_failed":      0,
        })
    logger.info("🔄 Estado reseteado")
