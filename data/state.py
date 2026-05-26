"""
data/state.py

Estado global del sistema con persistencia mínima en disco.
Sobrevive reinicios por sleep de Render Free.

LIMITACIÓN CONOCIDA:
/tmp se borra con cada deploy nuevo.
Suficiente para reinicios por inactividad.
En el futuro esto se reemplaza por SQLite/PostgreSQL
sin cambiar el resto del código.

#9 Multi-símbolo: positions[symbol] como estructura principal.
   Campos planos legacy mantenidos temporalmente para compatibilidad.
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
    # — sistema —
    "emergency":                    False,
    "emergency_reason":             None,
    "last_signal":                  None,
    "symbol":                       None,
    "blocked":                      False,
    "last_webhook_time":            None,
    "last_reconciler_time":         None,
    "last_webhook_signal":          None,
    "webhooks_received":            0,
    "webhooks_ok":                  0,
    "webhooks_failed":              0,
    "started_at":                   None,
    # — detección actividad externa (#3/#4) —
    "our_client_order_ids":         [],
    "external_close_detected":      False,
    "external_activity_detected":   False,
    # — #9 MULTI-SÍMBOLO — estructura principal —
    "positions": {},
    # — LEGACY — campos planos para compatibilidad temporal —
    "position_long":                False,
    "position_short":               False,
    "position_symbol":              None,
    "entry_price_long":             None,
    "entry_price_short":            None,
    "entry_qty_long":               None,
    "entry_qty_short":              None,
    "pyramid_long_count":           0,
    "pyramid_short_count":          0,
    "last_entry_bar_time":          None,
    "last_entry_bar_tf":            None,
}


# ============================================================
# 🏗️ HELPERS INTERNOS — positions[symbol]
# ============================================================

def _default_position() -> dict:
    return {
        "long":                False,
        "short":               False,
        "entry_price_long":    None,
        "entry_price_short":   None,
        "entry_qty_long":      None,
        "entry_qty_short":     None,
        "pyramid_long_count":  0,
        "pyramid_short_count": 0,
        "last_entry_bar_time": None,
        "last_entry_bar_tf":   None,
    }

def _get_pos(symbol: str) -> dict:
    """Devuelve posición del símbolo, creando entrada vacía si no existe."""
    if symbol not in _state["positions"]:
        _state["positions"][symbol] = _default_position()
    return _state["positions"][symbol]


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
        # Asegurar que positions existe tras cargar (por si viene de versión anterior)
        if "positions" not in _state:
            _state["positions"] = {}
        logger.info(f"✅ Estado restaurado desde disco: {STATE_FILE}")
        logger.info(f"   last_signal:               {_state.get('last_signal')}")
        logger.info(f"   emergency:                 {_state.get('emergency')}")
        logger.info(f"   símbolos activos:          {list(_state['positions'].keys())}")
        logger.info(f"   external_close_detected:   {_state.get('external_close_detected')}")
        logger.info(f"   external_activity_detected:{_state.get('external_activity_detected')}")
    except Exception as e:
        logger.error(f"❌ Error cargando estado: {e} — arrancando desde cero")


# ============================================================
# 📊 ACCESO AL ESTADO
# ============================================================

def get_state() -> dict:
    with _lock:
        return _state.copy()

def get_position(symbol: str) -> dict:
    """
    Devuelve posición actual para un símbolo específico.
    Útil para reconciler y panel.
    """
    with _lock:
        return _get_pos(symbol).copy()

def get_all_positions() -> dict:
    """
    Devuelve todas las posiciones activas (con al menos un lado abierto).
    Útil para reconciler multi-símbolo y panel.
    """
    with _lock:
        return {
            sym: pos.copy()
            for sym, pos in _state["positions"].items()
            if pos.get("long") or pos.get("short")
        }

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
            "emergency":                    False,
            "emergency_reason":             None,
            "last_signal":                  None,
            "symbol":                       None,
            "blocked":                      False,
            "last_webhook_time":            None,
            "last_reconciler_time":         None,
            "last_webhook_signal":          None,
            "webhooks_received":            0,
            "webhooks_ok":                  0,
            "webhooks_failed":              0,
            "started_at":                   format_log_time(),
            "our_client_order_ids":         [],
            "external_close_detected":      False,
            "external_activity_detected":   False,
            # #9 — limpiar todas las posiciones
            "positions":                    {},
            # legacy
            "position_long":                False,
            "position_short":               False,
            "position_symbol":              None,
            "entry_price_long":             None,
            "entry_price_short":            None,
            "entry_qty_long":               None,
            "entry_qty_short":              None,
            "pyramid_long_count":           0,
            "pyramid_short_count":          0,
            "last_entry_bar_time":          None,
            "last_entry_bar_tf":            None,
        })
    save_state()
    logger.info("🔄 Estado reseteado completamente")


# ============================================================
# 📍 POSICIONES — #9 multi-símbolo + legacy sync
# ============================================================

def update_position(symbol: str, has_long: bool, has_short: bool):
    """
    Actualiza posición para un símbolo.
    Escribe en positions[symbol] + mantiene campos legacy sincronizados.
    """
    with _lock:
        pos = _get_pos(symbol)
        pos["long"]  = has_long
        pos["short"] = has_short

        if not has_long:
            pos["entry_price_long"]    = None
            pos["entry_qty_long"]      = None
            pos["pyramid_long_count"]  = 0
        if not has_short:
            pos["entry_price_short"]   = None
            pos["entry_qty_short"]     = None
            pos["pyramid_short_count"] = 0

        # — sync legacy —
        _state["position_long"]   = has_long
        _state["position_short"]  = has_short
        _state["position_symbol"] = symbol if (has_long or has_short) else None
        if not has_long:
            _state["entry_price_long"]   = None
            _state["entry_qty_long"]     = None
            _state["pyramid_long_count"] = 0
        if not has_short:
            _state["entry_price_short"]   = None
            _state["entry_qty_short"]     = None
            _state["pyramid_short_count"] = 0

    save_state()
    logger.info(
        f"📍 Posición actualizada: {symbol} "
        f"LONG={has_long} SHORT={has_short}"
    )


def update_entry(symbol: str, side: str, price: float, qty: float):
    """
    Guarda precio y qty de entrada. Precio medio ponderado en pirámide.
    side: 'LONG' | 'SHORT'

    CAMBIO #9: primer parámetro es symbol.
    signal_handler.py actualizado para pasar symbol.
    """
    with _lock:
        pos = _get_pos(symbol)

        if side == "LONG":
            prev_qty   = pos.get("entry_qty_long")   or 0
            prev_price = pos.get("entry_price_long")  or price
            new_qty    = prev_qty + qty
            avg_price  = ((prev_price * prev_qty) + (price * qty)) / new_qty if new_qty else price
            pos["entry_qty_long"]   = new_qty
            pos["entry_price_long"] = round(avg_price, 8)
            # legacy sync
            _state["entry_qty_long"]   = new_qty
            _state["entry_price_long"] = round(avg_price, 8)

        elif side == "SHORT":
            prev_qty   = pos.get("entry_qty_short")   or 0
            prev_price = pos.get("entry_price_short")  or price
            new_qty    = prev_qty + qty
            avg_price  = ((prev_price * prev_qty) + (price * qty)) / new_qty if new_qty else price
            pos["entry_qty_short"]   = new_qty
            pos["entry_price_short"] = round(avg_price, 8)
            # legacy sync
            _state["entry_qty_short"]   = new_qty
            _state["entry_price_short"] = round(avg_price, 8)

    save_state()
    logger.info(f"📍 Entrada registrada: {symbol} {side} qty={qty} price={price}")


def increment_pyramid(symbol: str, side: str):
    """
    Incrementa contador pirámide para un símbolo y lado.

    CAMBIO #9: primer parámetro es symbol.
    signal_handler.py actualizado para pasar symbol.
    """
    with _lock:
        pos = _get_pos(symbol)

        if side == "LONG":
            pos["pyramid_long_count"] += 1
            count = pos["pyramid_long_count"]
            _state["pyramid_long_count"] = count  # legacy sync
        elif side == "SHORT":
            pos["pyramid_short_count"] += 1
            count = pos["pyramid_short_count"]
            _state["pyramid_short_count"] = count  # legacy sync

    save_state()
    logger.info(f"📈 Pirámide {symbol} {side}: {count} entradas")


def update_bar_time(symbol: str, bar_time: str, bar_tf: str):
    """
    Guarda timestamp y timeframe de última entrada para anti-duplicados.
    Antes estaba en update_state() directamente desde signal_handler.
    Ahora por símbolo.
    """
    with _lock:
        pos = _get_pos(symbol)
        pos["last_entry_bar_time"] = bar_time
        pos["last_entry_bar_tf"]   = bar_tf
        # legacy sync
        _state["last_entry_bar_time"] = bar_time
        _state["last_entry_bar_tf"]   = bar_tf
    save_state()


def get_bar_time(symbol: str) -> tuple:
    """
    Devuelve (last_entry_bar_time, last_entry_bar_tf) para un símbolo.
    Usado por signal_handler para anti-duplicados.
    """
    with _lock:
        pos = _get_pos(symbol)
        return (
            pos.get("last_entry_bar_time"),
            pos.get("last_entry_bar_tf"),
        )


# ============================================================
# 🧾 CLIENT ORDER IDS
# ============================================================

def register_our_order(client_order_id: str):
    """Guarda clientOrderIDs recientes. Máximo 20."""
    if not client_order_id:
        return
    with _lock:
        ids = _state.get("our_client_order_ids", [])
        if client_order_id not in ids:
            ids.append(client_order_id)
        _state["our_client_order_ids"] = ids[-20:]
    save_state()
    logger.info(f"🧾 clientOrderID registrado: {client_order_id}")

def get_our_order_ids() -> list:
    with _lock:
        return list(_state.get("our_client_order_ids", []))


# ============================================================
# 🚩 FLAGS
# ============================================================

def set_flag(key: str, value: bool):
    """
    Escribe flag booleano en state.
    Panel y Telegram solo leen — no calculan.
    """
    _VALID_FLAGS = {"external_close_detected", "external_activity_detected"}
    if key not in _VALID_FLAGS:
        logger.warning(f"⚠️ set_flag — key desconocida: {key} (ignorada)")
        return
    with _lock:
        _state[key] = value
    save_state()
    logger.info(f"🚩 Flag [{key}] = {value}")
