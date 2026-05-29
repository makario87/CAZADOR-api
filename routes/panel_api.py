"""
routes/panel_api.py
Endpoints que consume el Panel MVP.
Protegidos con PANEL_SECRET_TOKEN (variable de entorno en Render).
"""
import os
import time
from flask import Blueprint, jsonify, request
from logs.logger import get_logger
from data.database import get_db
from data.state import get_all_states
from core.emergency import is_emergency_active

logger = get_logger(__name__)
panel_bp = Blueprint("panel", __name__)

PANEL_TOKEN = os.environ.get("PANEL_SECRET_TOKEN", "")


def _auth(req):
    """Valida PANEL_SECRET_TOKEN en header X-Panel-Token."""
    if not PANEL_TOKEN:
        logger.error("❌ PANEL_SECRET_TOKEN no configurado en Render")
        return False
    token = req.headers.get("X-Panel-Token", "")
    return token == PANEL_TOKEN


def _fail_auth():
    return jsonify({"error": "Unauthorized"}), 401


# ─── GET /panel/status ────────────────────────────────────────────────────────
@panel_bp.route("/panel/status", methods=["GET"])
def panel_status():
    """Estado global del sistema."""
    if not _auth(request):
        return _fail_auth()

    # BD
    db_ok = False
    try:
        db = get_db()
        db.execute("SELECT 1")
        db_ok = True
    except Exception as e:
        logger.warning(f"⚠️ BD check failed: {e}")

    # BingX — comprobamos importando el módulo
    bingx_ok = False
    try:
        from brokers.bingx import get_balance
        bingx_ok = True  # si importa, el módulo está listo
    except Exception:
        pass

    # Reconciler — miramos state
    reconciler_ok = False
    try:
        states = get_all_states()
        reconciler_ok = True
    except Exception:
        pass

    # Emergency global
    emergency = False
    try:
        emergency = is_emergency_active(robot="global")
    except Exception:
        pass

    return jsonify({
        "server": True,
        "database": db_ok,
        "bingx_module": bingx_ok,
        "reconciler": reconciler_ok,
        "emergency_global": emergency,
        "timestamp": int(time.time())
    }), 200


# ─── GET /panel/users ─────────────────────────────────────────────────────────
@panel_bp.route("/panel/users", methods=["GET"])
def panel_users():
    """Lista de usuarios con estado de sus bots."""
    if not _auth(request):
        return _fail_auth()

    result = []
    try:
        db = get_db()

        # Usuarios activos
        users = db.execute(
            "SELECT id, name, email, plan, env, active FROM users WHERE active = 1"
        ).fetchall()

        # State en memoria por user_id
        states = get_all_states()

        for u in users:
            uid = u["id"]
            user_state = states.get(str(uid), {})

            bots = []
            for symbol, sym_state in user_state.items():
                bots.append({
                    "symbol": symbol,
                    "side": sym_state.get("side", "NONE"),
                    "pyramid_count": sym_state.get("pyramid_count", 0),
                    "emergency": sym_state.get("emergency", False),
                    "last_signal": sym_state.get("last_signal", None),
                })

            # Última operación de BD
            last_trade = db.execute(
                """SELECT signal, symbol, side, timestamp
                   FROM trades
                   WHERE user_id = ?
                   ORDER BY timestamp DESC LIMIT 1""",
                (str(uid),)
            ).fetchone()

            result.append({
                "id": uid,
                "name": u["name"],
                "email": u["email"],
                "plan": u["plan"],
                "env": u["env"],
                "active": bool(u["active"]),
                "bots": bots,
                "last_trade": dict(last_trade) if last_trade else None,
            })

    except Exception as e:
        logger.error(f"❌ panel/users error: {e}")
        return jsonify({"error": str(e)}), 500

    return jsonify({"users": result}), 200


# ─── GET /panel/alerts ────────────────────────────────────────────────────────
@panel_bp.route("/panel/alerts", methods=["GET"])
def panel_alerts():
    """Últimas alertas y errores del sistema."""
    if not _auth(request):
        return _fail_auth()

    alerts = []
    try:
        db = get_db()

        # Últimos trades con resultado error o warning
        trades = db.execute(
            """SELECT user_id, robot_id, symbol, signal, result, timestamp
               FROM trades
               WHERE result IN ('error', 'warning', 'failed')
               ORDER BY timestamp DESC LIMIT 20"""
        ).fetchall()

        for t in trades:
            alerts.append({
                "type": "trade_error",
                "user_id": t["user_id"],
                "robot_id": t["robot_id"],
                "symbol": t["symbol"],
                "signal": t["signal"],
                "result": t["result"],
                "timestamp": t["timestamp"],
            })

        # States con emergency activo
        states = get_all_states()
        for uid, user_state in states.items():
            for symbol, sym_state in user_state.items():
                if sym_state.get("emergency"):
                    alerts.append({
                        "type": "emergency",
                        "user_id": uid,
                        "symbol": symbol,
                        "timestamp": None,
                    })

    except Exception as e:
        logger.error(f"❌ panel/alerts error: {e}")
        return jsonify({"error": str(e)}), 500

    return jsonify({"alerts": alerts}), 200
