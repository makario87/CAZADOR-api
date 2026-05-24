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
    # — posición activa —
    "position_long":         False,
    "position_short":        False,
    "position_symbol":       None,
    # — datos entrada para PnL futuro —
    "entry_price_long":      None,   # precio medio entrada LONG
    "entry_price_short":     None,   # precio medio entrada SHORT
    "entry_qty_long":        None,   # qty total abierta LONG
    "entry_qty_short":       None,   # qty total abierta SHORT
    # — control pirámide —
    "pyramid_long_count":    0,
    "pyramid_short_count":   0,
}

# ============================================================
# 💾 PERSISTENCIA
# ============================================================

def save_state():
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(_state, f, indent=2)
    except Exception as e:
        logger.error(f"❌ Error guardando estado: {e}")

def load_state():
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
        logger.info(f"   emergency:   {_state.get('emergency')}")
    except Exception as e:
        logger.error(f"❌ Error cargando estado: {e} — arrancando desde cero")

# ============================================================
# 📊 ACCESO AL ESTADO
# ============================================================

def get_state() -> dict:
    with _lock:
        return _state.copy()

def update_state(updates: dict):
    with _lock:
        _state.update(updates)
    save_state()
    logger.info(f"📊 Estado actualizado: {updates}")

def record_webhook(signal: str, ok: bool):
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
    with _lock:
        _state["last_reconciler_time"] = format_log_time()
    save_state()

def reset_state():
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
            "position_long":         False,
            "position_short":        False,
            "position_symbol":       None,
            "entry_price_long":      None,
            "entry_price_short":     None,
            "entry_qty_long":        None,
            "entry_qty_short":       None,
            "pyramid_long_count":    0,
            "pyramid_short_count":   0,
        })
    save_state()
    logger.info("🔄 Estado reseteado completamente")

def update_position(symbol: str, has_long: bool, has_short: bool):
    """
    Actualiza qué posición cree Python que tiene abierta.
    Para registrar precio/qty de entrada usar update_entry().
    """
    with _lock:
        _state["position_long"]   = has_long
        _state["position_short"]  = has_short
        _state["position_symbol"] = symbol if (has_long or has_short) else None
        # Al cerrar completamente, limpiar datos de entrada
        if not has_long:
            _state["entry_price_long"] = None
            _state["entry_qty_long"]   = None
            _state["pyramid_long_count"] = 0
        if not has_short:
            _state["entry_price_short"] = None
            _state["entry_qty_short"]   = None
            _state["pyramid_short_count"] = 0
    save_state()
    logger.info(
        f"📍 Posición actualizada: "
        f"LONG={has_long} SHORT={has_short} symbol={symbol}"
    )

def update_entry(side: str, price: float, qty: float):
    """
    Guarda precio y qty de entrada para calcular PnL al cerrar.
    side: 'LONG' | 'SHORT'
    En pirámide: hace precio medio ponderado.
    """
    with _lock:
        if side == "LONG":
            prev_qty   = _state.get("entry_qty_long")   or 0
            prev_price = _state.get("entry_price_long") or price
            new_qty    = prev_qty + qty
            # Precio medio ponderado
            avg_price  = ((prev_price * prev_qty) + (price * qty)) / new_qty if new_qty else price
            _state["entry_qty_long"]   = new_qty
            _state["entry_price_long"] = round(avg_price, 8)
        elif side == "SHORT":
            prev_qty   = _state.get("entry_qty_short")   or 0
            prev_price = _state.get("entry_price_short") or price
            new_qty    = prev_qty + qty
            avg_price  = ((prev_price * prev_qty) + (price * qty)) / new_qty if new_qty else price
            _state["entry_qty_short"]   = new_qty
            _state["entry_price_short"] = round(avg_price, 8)
    save_state()
    logger.info(f"📍 Entrada registrada: {side} qty={qty} price={price}")

def increment_pyramid(side: str):
    """Incrementa el contador de pirámide al abrir una entrada."""
    with _lock:
        if side == "LONG":
            _state["pyramid_long_count"] += 1
            count = _state["pyramid_long_count"]

        elif side == "SHORT":
            _state["pyramid_short_count"] += 1
            count = _state["pyramid_short_count"]

    save_state()

    logger.info(f"📈 Pirámide {side}: {count} entradas abiertas")
