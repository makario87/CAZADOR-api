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
from brokers.bingx import get_balance_for_user
from data.users    import (create_user, get_user, get_all_users,
                           update_user, deactivate_user, get_users_summary)
from data.api_keys import (
    add_api_key,
    list_api_keys,
    deactivate_api_key,
    has_active_api_key,
    get_api_key
)
from data.audit    import get_recent_events, get_error_events

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


# ─── GET /panel/users/summary ────────────────────────────────────────────────
@panel_bp.route("/panel/users/summary", methods=["GET"])
def panel_users_summary():
    """Resumen numérico de usuarios para el panel."""
    if not _auth(request):
        return _fail_auth()
    try:
        return jsonify(get_users_summary()), 200
    except Exception as e:
        logger.error(f"❌ panel/users/summary error: {e}")
        return jsonify({"error": str(e)}), 500


# ─── GET /panel/users/<id> ───────────────────────────────────────────────────
@panel_bp.route("/panel/users/<int:user_id>", methods=["GET"])
def panel_user_detail(user_id):
    """Detalle de un usuario concreto."""
    if not _auth(request):
        return _fail_auth()
    try:
        user = get_user(user_id)
        if not user:
            return jsonify({"error": "Usuario no encontrado"}), 404
        user["has_api_key"] = has_active_api_key(user_id)
        return jsonify(user), 200
    except Exception as e:
        logger.error(f"❌ panel/users/{user_id} error: {e}")
        return jsonify({"error": str(e)}), 500


# ─── POST /panel/users ───────────────────────────────────────────────────────
@panel_bp.route("/panel/users", methods=["POST"])
def panel_create_user():
    """Crea un usuario nuevo."""
    if not _auth(request):
        return _fail_auth()
    try:
        data = request.get_json(force=True) or {}
        name  = data.get("name", "").strip()
        if not name:
            return jsonify({"error": "name es obligatorio"}), 400

        user_id = create_user(
            name        = name,
            email       = data.get("email"),
            telegram_id = data.get("telegram_id"),
            plan        = data.get("plan", "free"),
            env         = data.get("env", "demo")
        )
        return jsonify({"ok": True, "user_id": user_id}), 201

    except ValueError as e:
        return jsonify({"error": str(e)}), 409   # email duplicado
    except Exception as e:
        logger.error(f"❌ panel/users POST error: {e}")
        return jsonify({"error": str(e)}), 500


# ─── PUT /panel/users/<id> ───────────────────────────────────────────────────
@panel_bp.route("/panel/users/<int:user_id>", methods=["PUT"])
def panel_update_user(user_id):
    """Actualiza campos de un usuario."""
    if not _auth(request):
        return _fail_auth()
    try:
        data = request.get_json(force=True) or {}
        if not data:
            return jsonify({"error": "Sin campos para actualizar"}), 400

        ok = update_user(user_id, **data)
        if not ok:
            return jsonify({"error": "Usuario no encontrado"}), 404
        return jsonify({"ok": True}), 200

    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        logger.error(f"❌ panel/users/{user_id} PUT error: {e}")
        return jsonify({"error": str(e)}), 500


# ─── DELETE /panel/users/<id> ────────────────────────────────────────────────
@panel_bp.route("/panel/users/<int:user_id>", methods=["DELETE"])
def panel_deactivate_user(user_id):
    """Desactiva un usuario (soft delete)."""
    if not _auth(request):
        return _fail_auth()
    try:
        ok = deactivate_user(user_id)
        if not ok:
            return jsonify({"error": "Usuario no encontrado"}), 404
        return jsonify({"ok": True}), 200
    except Exception as e:
        logger.error(f"❌ panel/users/{user_id} DELETE error: {e}")
        return jsonify({"error": str(e)}), 500


# ─── GET /panel/users/<id>/apikeys ───────────────────────────────────────────
@panel_bp.route("/panel/users/<int:user_id>/apikeys", methods=["GET"])
def panel_list_apikeys(user_id):
    """Lista API keys de un usuario (sin descifrar)."""
    if not _auth(request):
        return _fail_auth()
    try:
        if not get_user(user_id):
            return jsonify({"error": "Usuario no encontrado"}), 404
        keys = list_api_keys(user_id)
        return jsonify({"api_keys": keys}), 200
    except Exception as e:
        logger.error(f"❌ panel/users/{user_id}/apikeys GET error: {e}")
        return jsonify({"error": str(e)}), 500


# ─── POST /panel/users/<id>/apikeys ──────────────────────────────────────────
@panel_bp.route("/panel/users/<int:user_id>/apikeys", methods=["POST"])
def panel_add_apikey(user_id):
    """Añade una API key cifrada a un usuario."""
    if not _auth(request):
        return _fail_auth()
    try:
        if not get_user(user_id):
            return jsonify({"error": "Usuario no encontrado"}), 404

        data   = request.get_json(force=True) or {}
        key    = data.get("key", "").strip()
        secret = data.get("secret", "").strip()

        if not key or not secret:
            return jsonify({"error": "key y secret son obligatorios"}), 400

        api_key_id = add_api_key(
            user_id  = user_id,
            key      = key,
            secret   = secret,
            exchange = data.get("exchange", "bingx"),
            env      = data.get("env", "demo")
        )
        return jsonify({"ok": True, "api_key_id": api_key_id}), 201

    except Exception as e:
        logger.error(f"❌ panel/users/{user_id}/apikeys POST error: {e}")
        return jsonify({"error": str(e)}), 500


# ─── DELETE /panel/users/<id>/apikeys/<key_id> ───────────────────────────────
@panel_bp.route("/panel/users/<int:user_id>/apikeys/<int:key_id>", methods=["DELETE"])
def panel_deactivate_apikey(user_id, key_id):
    """Desactiva una API key (soft delete)."""
    if not _auth(request):
        return _fail_auth()
    try:
        ok = deactivate_api_key(key_id, user_id)
        if not ok:
            return jsonify({"error": "API key no encontrada"}), 404
        return jsonify({"ok": True}), 200
    except Exception as e:
        logger.error(f"❌ panel/users/{user_id}/apikeys/{key_id} DELETE error: {e}")
        return jsonify({"error": str(e)}), 500


# ─── GET /panel/audit ────────────────────────────────────────────────────────
@panel_bp.route("/panel/audit", methods=["GET"])
def panel_audit():
    """Eventos recientes del audit_log."""
    if not _auth(request):
        return _fail_auth()
    try:
        level      = request.args.get("level")
        event_type = request.args.get("event_type")
        limit      = min(int(request.args.get("limit", 100)), 500)

        events = get_recent_events(limit=limit, level=level, event_type=event_type)
        return jsonify({"events": events}), 200
    except Exception as e:
        logger.error(f"❌ panel/audit error: {e}")
        return jsonify({"error": str(e)}), 500


# ─── GET /panel/audit/errors ─────────────────────────────────────────────────
@panel_bp.route("/panel/audit/errors", methods=["GET"])
def panel_audit_errors():
    """Errores y warnings recientes — para alertas críticas."""
    if not _auth(request):
        return _fail_auth()
    try:
        limit  = min(int(request.args.get("limit", 50)), 200)
        events = get_error_events(limit=limit)
        return jsonify({"events": events}), 200
    except Exception as e:
        logger.error(f"❌ panel/audit/errors error: {e}")
        return jsonify({"error": str(e)}), 500


# ─── GET /panel/users/<id>/balance ───────────────────────────────────────────
@panel_bp.route("/panel/users/<int:user_id>/balance", methods=["GET"])
def panel_user_balance(user_id):
    """
    Consulta balance BingX real del usuario.
    Descifra sus keys, llama a BingX con ellas, devuelve balance/equity/margen.
    Nunca expone keys en la respuesta.
    """
    if not _auth(request):
        return _fail_auth()

    import time as _time

    try:
        user = get_user(user_id)
        if not user:
            return jsonify({"error": "Usuario no encontrado"}), 404

        env      = user.get("env", "demo")
        api_data = get_api_key(user_id, exchange="bingx", env=env)

        if not api_data:
            return jsonify({
                "error":    "Sin API key activa",
                "env":      env,
                "source":   "bingx",
                "last_update": int(_time.time())
            }), 404

        # Seleccionar base_url según env del usuario
        if env == "live":
            base_url = "https://open-api.bingx.com"
        else:
            base_url = "https://open-api-vst.bingx.com"

        result = get_balance_for_user(
            api_key    = api_data["key"],
            api_secret = api_data["secret"],
            base_url   = base_url,
        )

        if "error" in result:
            return jsonify({
                "error":       result["error"],
                "env":         env,
                "source":      "bingx",
                "last_update": int(_time.time())
            }), 502

        return jsonify({
            "balance":          result["balance"],
            "equity":           result["equity"],
            "available_margin": result["available_margin"],
            "used_margin":      result["used_margin"],
            "env":              env,
            "source":           "bingx",
            "last_update":      int(_time.time())
        }), 200

    except Exception as e:
        logger.error(f"❌ panel/users/{user_id}/balance error: {e}")
        return jsonify({"error": str(e)}), 500

# ─── POST /panel/login ───────────────────────────────────────────────────────
@panel_bp.route("/panel/login", methods=["POST"])
def panel_login():
    """
    Valida credenciales del panel.
    No requiere token previo — es el endpoint público de autenticación.
    Devuelve ok:true si las credenciales son correctas.
    """
    try:
        data     = request.get_json(force=True) or {}
        username = data.get("username", "").strip()
        password = data.get("password", "").strip()

        if not username or not password:
            return jsonify({"ok": False, "error": "Credenciales requeridas"}), 400

        if username == "admin" and password == PANEL_TOKEN:
            logger.info(f"✅ Login panel correcto — user={username}")
            return jsonify({"ok": True}), 200
        else:
            logger.warning(f"⚠️ Login panel fallido — user={username}")
            return jsonify({"ok": False, "error": "Credenciales incorrectas"}), 401

    except Exception as e:
        logger.error(f"❌ panel/login error: {e}")
        return jsonify({"error": str(e)}), 500
