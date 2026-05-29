"""
routes/panel_api.py
Endpoints que consume el Panel MVP.
Protegidos con PANEL_SECRET_TOKEN (variable de entorno en Render).
"""
import os
import time
from flask import Blueprint, jsonify, request
from logs.logger import get_logger
from data.database import get_conn, db_fetchall, db_fetchone
from data.state import get_all_user_ids, get_state, get_all_positions
from core.emergency import is_emergency

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
        get_conn().execute("SELECT 1")
        db_ok = True
    except Exception as e:
        logger.warning(f"⚠️ BD check failed: {e}")

    # BingX module
    bingx_ok = False
    try:
        from brokers.bingx import ping_bingx
        bingx_ok = True
    except Exception:
        pass

    # Reconciler — si hay user_ids en memoria el reconciler está vivo
    reconciler_ok = False
    try:
        get_all_user_ids()
        reconciler_ok = True
    except Exception:
        pass

    # Emergency global
    emergency = False
    try:
        emergency = is_emergency()
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
        users = db_fetchall(
            "SELECT id, name, email, plan, env, active FROM users WHERE active = 1"
        )

        user_ids = get_all_user_ids()

        for u in users:
            uid = str(u["id"])
            bots = []

            if uid in user_ids:
                st = get_state(uid)
                positions = st.get("positions", {})
                for symbol, pos in positions.items():
                    if pos.get("long") or pos.get("short"):
                        bots.append({
                            "symbol":        symbol,
                            "side":          "LONG" if pos.get("long") else "SHORT",
                            "pyramid_count": pos.get("pyramid_long_count", 0) if pos.get("long") else pos.get("pyramid_short_count", 0),
                            "emergency":     st.get("emergency", False),
                            "last_signal":   st.get("last_signal"),
                        })

            last_trade = db_fetchone(
                """SELECT signal, symbol, side, timestamp
                   FROM trades
                   WHERE user_id = ?
                   ORDER BY timestamp DESC LIMIT 1""",
                (uid,)
            )

            result.append({
                "id":         u["id"],
                "name":       u["name"],
                "email":      u["email"],
                "plan":       u["plan"],
                "env":        u["env"],
                "active":     bool(u["active"]),
                "bots":       bots,
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
        trades = db_fetchall(
            """SELECT user_id, robot_id, symbol, signal, result, timestamp
               FROM trades
               WHERE result IN ('error', 'warning', 'failed')
               ORDER BY timestamp DESC LIMIT 20"""
        )

        for t in trades:
            alerts.append({
                "type":      "trade_error",
                "user_id":   t["user_id"],
                "robot_id":  t["robot_id"],
                "symbol":    t["symbol"],
                "signal":    t["signal"],
                "result":    t["result"],
                "timestamp": t["timestamp"],
            })

        # Emergency activos en memoria
        for uid in get_all_user_ids():
            st = get_state(uid)
            if st.get("emergency"):
                alerts.append({
                    "type":      "emergency",
                    "user_id":   uid,
                    "symbol":    st.get("position_symbol", "—"),
                    "result":    "emergency",
                    "timestamp": None,
                })

    except Exception as e:
        logger.error(f"❌ panel/alerts error: {e}")
        return jsonify({"error": str(e)}), 500

    return jsonify({"alerts": alerts}), 200
