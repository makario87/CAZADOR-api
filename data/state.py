"""
data/state.py

Estado global del sistema con persistencia en SQLite.
Sesión 7 — #12 BD real: migrado de /tmp JSON a SQLite.
Sesión 8 — #12b multi-usuario: _states[user_id] con user_id="default" como puente.

Backward compatible total:
  Todas las funciones aceptan user_id=DEFAULT_USER ("default").
  Código existente sin user_id sigue funcionando igual.

#9 Multi-símbolo: positions[symbol] como estructura principal.
   Campos planos legacy mantenidos temporalmente para compatibilidad.
"""
import json
import threading
from utils.time_utils import format_log_time
from data.database import db_execute, db_fetchone, db_fetchall
from logs.logger import get_logger

logger = get_logger(__name__)

# ============================================================
# 👤 MULTI-USUARIO — #12b
# ============================================================
DEFAULT_USER = "default"

_lock   = threading.Lock()
_states = {}   # { user_id: { ...state por usuario... } }


# ============================================================
# 🏗️ ESTADO BASE POR USUARIO
# ============================================================

def _default_state() -> dict:
    return {
        # — sistema —
        "emergency":                    False,
        "emergency_reason":             None,
        "emergency_by_robot":           {},
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
        # — #9 MULTI-SÍMBOLO —
        "positions":                    {},
        # — LEGACY —
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


def _get_user_state(user_id: str = DEFAULT_USER) -> dict:
    """Devuelve state del usuario, creando entrada vacía si no existe."""
    if user_id not in _states:
        _states[user_id] = _default_state()
    return _states[user_id]


# ============================================================
# 🏗️ HELPERS INTERNOS — positions[symbol]
# ============================================================

def _default_position() -> dict:
    return {
        "long":                      False,
        "short":                     False,
        "entry_price_long":          None,
        "entry_price_short":         None,
        "entry_qty_long":            None,
        "entry_qty_short":           None,
        "pyramid_long_count":        0,
        "pyramid_short_count":       0,
        "last_entry_bar_time":       None,
        "last_entry_bar_tf":         None,
        "sl_broker_order_id_long":   None,
        "sl_broker_order_id_short":  None,
    }


def _get_pos(symbol: str, user_id: str = DEFAULT_USER) -> dict:
    """Devuelve posición del símbolo para un usuario, creando entrada vacía si no existe."""
    st = _get_user_state(user_id)
    if symbol not in st["positions"]:
        st["positions"][symbol] = _default_position()
    return st["positions"][symbol]


# ============================================================
# 💾 PERSISTENCIA
# ============================================================

def save_state(user_id: str = DEFAULT_USER):
    try:
        key = f"state:{user_id}"
        db_execute(
            """INSERT INTO system_state (key, value, updated_at)
               VALUES (?, ?, datetime('now'))
               ON CONFLICT(key) DO UPDATE SET value=excluded.value,
               updated_at=excluded.updated_at""",
            (key, json.dumps(_get_user_state(user_id)))
        )
    except Exception as e:
        logger.error(f"❌ Error guardando estado [{user_id}]: {e}")


def load_state():
    try:
        rows = db_fetchall(
            "SELECT key, value FROM system_state WHERE key LIKE 'state:%'"
        )
        if not rows:
            # compatibilidad: intentar leer key='main' de versión anterior
            row = db_fetchone("SELECT value FROM system_state WHERE key='main'")
            if row:
                saved = json.loads(row["value"])
                st = _get_user_state(DEFAULT_USER)
                st.update(saved)
                if "positions" not in st:
                    st["positions"] = {}
                if "emergency_by_robot" not in st:
                    st["emergency_by_robot"] = {}
                logger.info("✅ Estado legacy 'main' migrado a user='default'")
            else:
                logger.info("📂 No hay estado previo — arrancando desde cero")
            return
        for row in rows:
            user_id = row["key"].replace("state:", "")
            saved   = json.loads(row["value"])
            st      = _get_user_state(user_id)
            st.update(saved)
            if "positions" not in st:
                st["positions"] = {}
            if "emergency_by_robot" not in st:
                st["emergency_by_robot"] = {}
            logger.info(f"✅ Estado restaurado [{user_id}]")
            logger.info(f"   last_signal:    {st.get('last_signal')}")
            logger.info(f"   emergency:      {st.get('emergency')}")
            logger.info(f"   símbolos:       {list(st['positions'].keys())}")
    except Exception as e:
        logger.error(f"❌ Error cargando estado: {e} — arrancando desde cero")


# ============================================================
# 📊 ACCESO AL ESTADO
# ============================================================

def get_state(user_id: str = DEFAULT_USER) -> dict:
    with _lock:
        return _get_user_state(user_id).copy()


def get_all_user_ids() -> list:
    """Devuelve lista de user_ids activos en memoria. Útil para reconciler y panel."""
    with _lock:
        return list(_states.keys())


def get_position(symbol: str, user_id: str = DEFAULT_USER) -> dict:
    with _lock:
        return _get_pos(symbol, user_id).copy()


def get_all_positions(user_id: str = DEFAULT_USER) -> dict:
    with _lock:
        st = _get_user_state(user_id)
        return {
            sym: pos.copy()
            for sym, pos in st["positions"].items()
            if pos.get("long") or pos.get("short")
        }


def update_state(updates: dict, user_id: str = DEFAULT_USER):
    with _lock:
        _get_user_state(user_id).update(updates)
    save_state(user_id)
    logger.info(f"📊 Estado actualizado [{user_id}]: {updates}")


def record_webhook(signal: str, ok: bool, user_id: str = DEFAULT_USER):
    with _lock:
        st = _get_user_state(user_id)
        st["last_webhook_time"]   = format_log_time()
        st["last_webhook_signal"] = signal
        st["webhooks_received"]  += 1
        if ok:
            st["webhooks_ok"]    += 1
        else:
            st["webhooks_failed"] += 1
    save_state(user_id)


def record_reconciler(user_id: str = DEFAULT_USER):
    with _lock:
        _get_user_state(user_id)["last_reconciler_time"] = format_log_time()
    save_state(user_id)


def reset_state(user_id: str = DEFAULT_USER):
    with _lock:
        _states[user_id] = _default_state()
        _states[user_id]["started_at"] = format_log_time()
    save_state(user_id)
    logger.info(f"🔄 Estado reseteado [{user_id}]")


# ============================================================
# 📍 POSICIONES — #9 multi-símbolo + legacy sync
# ============================================================

def update_position(symbol: str, has_long: bool, has_short: bool,
                    user_id: str = DEFAULT_USER):
    with _lock:
        st  = _get_user_state(user_id)
        pos = _get_pos(symbol, user_id)
        pos["long"]  = has_long
        pos["short"] = has_short

        if not has_long:
            pos["entry_price_long"]         = None
            pos["entry_qty_long"]           = None
            pos["pyramid_long_count"]       = 0
            pos["sl_broker_order_id_long"]  = None

        if not has_short:
            pos["entry_price_short"]        = None
            pos["entry_qty_short"]          = None
            pos["pyramid_short_count"]      = 0
            pos["sl_broker_order_id_short"] = None

        # legacy sync
        st["position_long"]   = has_long
        st["position_short"]  = has_short
        st["position_symbol"] = symbol if (has_long or has_short) else None

        if not has_long:
            st["entry_price_long"]   = None
            st["entry_qty_long"]     = None
            st["pyramid_long_count"] = 0
        if not has_short:
            st["entry_price_short"]   = None
            st["entry_qty_short"]     = None
            st["pyramid_short_count"] = 0

    save_state(user_id)
    logger.info(
        f"📍 Posición actualizada [{user_id}]: {symbol} "
        f"LONG={has_long} SHORT={has_short}"
    )


def update_entry(symbol: str, side: str, price: float, qty: float,
                 user_id: str = DEFAULT_USER):
    with _lock:
        st  = _get_user_state(user_id)
        pos = _get_pos(symbol, user_id)

        if side == "LONG":
            prev_qty   = pos.get("entry_qty_long")  or 0
            prev_price = pos.get("entry_price_long") or price
            new_qty    = prev_qty + qty
            avg_price  = ((prev_price * prev_qty) + (price * qty)) / new_qty if new_qty else price
            pos["entry_qty_long"]   = new_qty
            pos["entry_price_long"] = round(avg_price, 8)
            st["entry_qty_long"]    = new_qty
            st["entry_price_long"]  = round(avg_price, 8)

        elif side == "SHORT":
            prev_qty   = pos.get("entry_qty_short")  or 0
            prev_price = pos.get("entry_price_short") or price
            new_qty    = prev_qty + qty
            avg_price  = ((prev_price * prev_qty) + (price * qty)) / new_qty if new_qty else price
            pos["entry_qty_short"]   = new_qty
            pos["entry_price_short"] = round(avg_price, 8)
            st["entry_qty_short"]    = new_qty
            st["entry_price_short"]  = round(avg_price, 8)

    save_state(user_id)
    logger.info(f"📍 Entrada registrada [{user_id}]: {symbol} {side} qty={qty} price={price}")


def increment_pyramid(symbol: str, side: str, user_id: str = DEFAULT_USER):
    with _lock:
        st  = _get_user_state(user_id)
        pos = _get_pos(symbol, user_id)

        if side == "LONG":
            pos["pyramid_long_count"] += 1
            count = pos["pyramid_long_count"]
            st["pyramid_long_count"]  = count
        elif side == "SHORT":
            pos["pyramid_short_count"] += 1
            count = pos["pyramid_short_count"]
            st["pyramid_short_count"]  = count

    save_state(user_id)
    logger.info(f"📈 Pirámide [{user_id}] {symbol} {side}: {count}")

def get_pyramid(symbol: str, side: str, user_id: str = DEFAULT_USER) -> int:
    """
    Devuelve el contador actual de entradas de pirámide para un símbolo y lado.
    side: LONG | SHORT
    Usado por signal_handler para control de pirámide por usuario.
    """
    with _lock:
        pos = _get_pos(symbol, user_id)
        if side == "LONG":
            return pos.get("pyramid_long_count", 0)
        elif side == "SHORT":
            return pos.get("pyramid_short_count", 0)
        return 0


def reset_pyramid(symbol: str, side: str, user_id: str = DEFAULT_USER):
    """
    Resetea el contador de pirámide para un símbolo y lado.
    Se llama cuando BingX confirma que no hay posición abierta
    pero el state interno tiene contador > 0 — indica desync o restart.
    side: LONG | SHORT
    """
    with _lock:
        st  = _get_user_state(user_id)
        pos = _get_pos(symbol, user_id)

        if side == "LONG":

            if pos.get("pyramid_long_count", 0) > 0:
                logger.warning(
                    f"⚠️ reset_pyramid [{user_id}] {symbol} LONG — "
                    f"contador era {pos['pyramid_long_count']}, "
                    f"BingX no tiene posición → reset"
                )

            pos["pyramid_long_count"] = 0
            st["pyramid_long_count"]  = 0

        elif side == "SHORT":

            if pos.get("pyramid_short_count", 0) > 0:
                logger.warning(
                    f"⚠️ reset_pyramid [{user_id}] {symbol} SHORT — "
                    f"contador era {pos['pyramid_short_count']}, "
                    f"BingX no tiene posición → reset"
                )

            pos["pyramid_short_count"] = 0
            st["pyramid_short_count"]  = 0

    save_state(user_id)

def update_bar_time(symbol: str, bar_time: str, bar_tf: str,
                    user_id: str = DEFAULT_USER):
    with _lock:
        st  = _get_user_state(user_id)
        pos = _get_pos(symbol, user_id)
        pos["last_entry_bar_time"] = bar_time
        pos["last_entry_bar_tf"]   = bar_tf
        st["last_entry_bar_time"]  = bar_time
        st["last_entry_bar_tf"]    = bar_tf
    save_state(user_id)


def get_bar_time(symbol: str, user_id: str = DEFAULT_USER) -> tuple:
    with _lock:
        pos = _get_pos(symbol, user_id)
        return (
            pos.get("last_entry_bar_time"),
            pos.get("last_entry_bar_tf"),
        )


# ============================================================
# 🧾 CLIENT ORDER IDS
# ============================================================

def register_our_order(client_order_id: str, user_id: str = DEFAULT_USER):
    if not client_order_id:
        return
    with _lock:
        st  = _get_user_state(user_id)
        ids = st.get("our_client_order_ids", [])
        if client_order_id not in ids:
            ids.append(client_order_id)
        st["our_client_order_ids"] = ids[-20:]
    save_state(user_id)
    logger.info(f"🧾 clientOrderID registrado [{user_id}]: {client_order_id}")


def get_our_order_ids(user_id: str = DEFAULT_USER) -> list:
    with _lock:
        return list(_get_user_state(user_id).get("our_client_order_ids", []))


# ============================================================
# 🚩 FLAGS
# ============================================================

def set_flag(key: str, value: bool, user_id: str = DEFAULT_USER):
    _VALID_FLAGS = {"external_close_detected", "external_activity_detected"}
    if key not in _VALID_FLAGS:
        logger.warning(f"⚠️ set_flag — key desconocida: {key} (ignorada)")
        return
    with _lock:
        _get_user_state(user_id)[key] = value
    save_state(user_id)
    logger.info(f"🚩 Flag [{user_id}][{key}] = {value}")


# ============================================================
# 🚨 EMERGENCY POR ROBOT
# ============================================================

def set_robot_emergency(robot: str, active: bool, reason: str = "",
                        user_id: str = DEFAULT_USER):
    with _lock:
        st     = _get_user_state(user_id)
        robots = st.setdefault("emergency_by_robot", {})
        robots[robot] = {"active": active, "reason": reason}

        any_active = any(r["active"] for r in robots.values())
        st["emergency"]        = any_active
        st["emergency_reason"] = reason if active else (
            next((r["reason"] for r in robots.values() if r["active"]), None)
        )
        st["blocked"] = any_active

    save_state(user_id)
    status = "ACTIVADA" if active else "RESUELTA"
    logger.info(f"🚨 Emergency [{user_id}][{robot}] {status}: {reason}")


def get_robot_emergency(robot: str, user_id: str = DEFAULT_USER) -> dict:
    with _lock:
        robots = _get_user_state(user_id).get("emergency_by_robot", {})
        return robots.get(robot, {"active": False, "reason": ""})


def is_any_emergency(user_id: str = DEFAULT_USER) -> bool:
    with _lock:
        return _get_user_state(user_id).get("emergency", False)


# ============================================================
# 🛡️ SL BROKER ORDER IDS — #11
# ============================================================

def set_sl_broker_order_id(symbol: str, side: str, order_id,
                           user_id: str = DEFAULT_USER):
    with _lock:
        pos = _get_pos(symbol, user_id)
        pos[f"sl_broker_order_id_{side.lower()}"] = order_id
    save_state(user_id)
    logger.info(f"🛡️ SL broker order_id [{user_id}][{symbol}][{side}] = {order_id}")


def get_sl_broker_order_id(symbol: str, side: str,
                           user_id: str = DEFAULT_USER):
    with _lock:
        pos = _get_pos(symbol, user_id)
        return pos.get(f"sl_broker_order_id_{side.lower()}")
