"""
data/state.py

Estado global del sistema con persistencia mínima en disco.
Sobrevive reinicios por sleep de Render Free.

LIMITACIÓN CONOCIDA:
/tmp se borra con cada deploy nuevo.
Suficiente para reinicios por inactividad.
En el futuro esto se reemplaza por SQLite/PostgreSQL
sin cambiar el resto del código.
"""
import json
import os
import threading
from utils.time_utils import format_log_time
from logs.logger import get_logger

logger = get_logger(__name__)

# ============================================================
# 📁 ARCHIVO DE PERSISTENCIA
# ============================================================
STATE_FILE = "/tmp/cazador_state.json"

_lock  = threading.Lock()
_state = {
    "emergency":             False,
    "emergency_reason":      None,
    "last_signal":           None,
    "symbol":                None,
    "blocked":               False,
    "last_webhook_time":     None,
    "last_reconciler_time":  None,
    "last_webhook_signal":   None,
    "webhooks_received":     0,
    "webhooks_ok":           0,
    "webhooks_failed":       0,
    "started_at":            None,
}

# ============================================================
# 💾 PERSISTENCIA
# ============================================================

def save_state():
    """Guarda el estado actual en disco."""
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(_state, f, indent=2)
    except Exception as e:
        logger.error(f"❌ Error guardando estado: {e}")

def load_state():
    """
    Carga el estado desde disco al arrancar.
    Si no existe el archivo arranca desde cero.
    """
    global _state
    if not os.path.exists(STATE_FILE):
        logger.info("📂 No hay estado previo — arrancando desde cero")
        return

    try:
        with open(STATE_FILE) as f:
            saved = json.load(f)
            _state.update(saved)
        logger.info(f"✅ Estado restaurado desde disco: {STATE_FILE}")
        logger.info(f"   last_signal: {_state.get('last_signal')}")
        logger.info(f"   last_webhook: {_state.get('last_webhook_time')}")
        logger.info(f"   emergency: {_state.get('emergency')}")
    except Exception as e:
        logger.error(f"❌ Error cargando estado: {e} — arrancando desde cero")

# ============================================================
# 📊 ACCESO AL ESTADO
# ============================================================

def get_state() -> dict:
    with _lock:
        return _state.copy()

def update_state(updates: dict):
    """Actualiza estado en RAM y persiste al disco."""
    with _lock:
        _state.update(updates)
    save_state()
    logger.info(f"📊 Estado actualizado: {updates}")

def record_webhook(signal: str, ok: bool):
    """Registra métricas de webhooks recibidos."""
    with _lock:
        _state["last_webhook_time"]   = format_log_time()
        _state["last_webhook_signal"] = signal
        _state["webhooks_received"]  += 1
        if ok:
            _state["webhooks_ok"]    += 1
        else:
            _state["webhooks_failed"] += 1
    save_state()

def record_reconciler():
    """Registra timestamp del último ciclo de reconciliación."""
    with _lock:
        _state["last_reconciler_time"] = format_log_time()
    save_state()

def reset_state():
    """Reset completo — útil para debug o emergencias."""
    with _lock:
        _state.update({
            "emergency":             False,
            "emergency_reason":      None,
            "last_signal":           None,
            "symbol":                None,
            "blocked":               False,
            "last_webhook_time":     None,
            "last_reconciler_time":  None,
            "last_webhook_signal":   None,
            "webhooks_received":     0,
            "webhooks_ok":           0,
            "webhooks_failed":       0,
            "started_at":            format_log_time(),
        })
    save_state()
    logger.info("🔄 Estado reseteado completamente")
