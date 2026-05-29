"""
app.py
Arranque principal del sistema CAZADOR → Python → BingX.
"""
from flask import Flask, jsonify
from flask_cors import CORS
from config.settings import DEMO_MODE, validate
from routes.webhook import webhook_bp
from routes.panel_api import panel_bp
from core.queue_manager import _workers, start_worker, DEFAULT_USER
from core.reconciler import start_reconciler
from core.emergency import (
    resolve_emergency,
    is_emergency,
    is_watchdog_alive,
    get_consecutive_fails,
)
from data.state import get_state, reset_state, load_state, update_state
from brokers.market_info import preload as preload_market
from data.trade_log import (
    load_trades,
    get_trades,
    get_summary,
    export_csv_string,
    clear_trades,
)
from reports.csv_exporter import export_csv
from brokers.bingx import get_balance, get_positions, cancel_order
from logs.logger import get_logger
from core.queue_manager import queue_size
from core.reconciler import is_alive as reconciler_alive
from utils.time_utils import format_log_time

logger = get_logger(__name__)

# ============================================================
# 🚀 CREAR APP FLASK
# ============================================================
app = Flask(__name__)

CORS(app, resources={
    r"/panel/*": {
        "origins": "https://central-bots-panel.onrender.com"
    }
})

app.register_blueprint(webhook_bp)
app.register_blueprint(panel_bp)

# ============================================================
# 🏠 PANEL BÁSICO
# ============================================================
@app.route("/", methods=["GET"])
def panel():
    """Panel de estado básico."""
    state = get_state()
    return jsonify({
        "status":      "🟢 online",
        "demo_mode":   DEMO_MODE,
        "emergency":   state.get("emergency"),
        "last_signal": state.get("last_signal"),
        "symbol":      state.get("symbol"),
    })

@app.route("/health", methods=["GET"])
def health():

    state = get_state()

    w = _workers.get(DEFAULT_USER)
    worker_alive = w is not None and w.is_alive()

    # #6 — ping BingX real con latencia
    import time as _time
    from brokers.bingx import ping_bingx

    t0 = _time.monotonic()

    bingx_ok = ping_bingx()

    bingx_latency_ms = round(
        (_time.monotonic() - t0) * 1000
    )

    return jsonify({
        "status":                       "🟢 online",
        "time_now":                     format_log_time(),
        "demo_mode":                    DEMO_MODE,
        "emergency":                    state.get("emergency"),
        "emergency_by_robot":           state.get("emergency_by_robot", {}),
        "blocked":                      state.get("blocked"),
        "queue_size":                   queue_size(),
        "worker_alive":                 worker_alive,
        "reconciler_alive":             reconciler_alive(),

        # WATCHDOG
        "watchdog_alive":               is_watchdog_alive(),
        "watchdog_consecutive_fails":   get_consecutive_fails(),

        # BINGX
        "bingx_reachable":              bingx_ok,
        "bingx_latency_ms":             bingx_latency_ms,

        # WEBHOOKS
        "last_webhook_time":            state.get("last_webhook_time"),
        "last_webhook_signal":          state.get("last_webhook_signal"),
        "last_reconciler_time":         state.get("last_reconciler_time"),

        # ESTADÍSTICAS
        "webhooks_received":            state.get("webhooks_received"),
        "webhooks_ok":                  state.get("webhooks_ok"),
        "webhooks_failed":              state.get("webhooks_failed"),

        # ESTADO GENERAL
        "started_at":                   state.get("started_at"),
        "last_signal":                  state.get("last_signal"),
        "symbol":                       state.get("symbol"),

        # FLAGS
        "external_close_detected":      state.get("external_close_detected"),
        "external_activity_detected":   state.get("external_activity_detected"),
    })

@app.route("/ping", methods=["GET"])
def ping():
    """Mantiene vivo el servidor en Render free tier."""

    response = jsonify({
        "status": "pong",
        "time":   format_log_time()
    })

    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    response.headers["Pragma"]        = "no-cache"

    return response, 200

@app.route("/state", methods=["GET"])
def state():
    """Estado completo del sistema."""
    return jsonify(get_state())

@app.route("/balance", methods=["GET"])
def balance():
    """Consulta balance real de BingX."""
    return jsonify(get_balance())

@app.route("/positions", methods=["GET"])
def positions():
    """Consulta posiciones abiertas en BingX."""
    symbol = request.args.get("symbol", "") if hasattr(positions, '__self__') else ""
    return jsonify(get_positions())

@app.route("/trades", methods=["GET"])
def trades():
    """Historial completo + resumen."""
    return jsonify({
        "summary": get_summary(),
        "trades":  get_trades()
    })

@app.route("/trades/csv", methods=["GET"])
def trades_csv():
    """Exporta historial persistente CSV."""
    from flask import Response

    csv_data = export_csv_string()

    if not csv_data:
        return jsonify({"message": "No hay trades"}), 200

    return Response(
        csv_data,
        mimetype="text/csv",
        headers={
            "Content-Disposition":
            "attachment;filename=cazador_trades.csv"
        }
    )

@app.route("/emergency/resolve", methods=["POST"])
def emergency_resolve():
    """
    Resuelve emergency manualmente desde el panel.
    Sin parámetro → resuelve TODOS los robots activos + GLOBAL.
    Con ?robot=CAZADOR → resuelve solo ese robot.
    """
    from flask import request as freq
    from data.state import get_state

    robot = freq.args.get("robot")

    if robot:
        resolve_emergency(robot=robot)
        return jsonify({"status": "emergency_resolved", "robot": robot})

    # Sin parámetro → resolver todos
    state = get_state()
    robots = state.get("emergency_by_robot", {})
    resolved = []

    for r in list(robots.keys()):
        resolve_emergency(robot=r)
        resolved.append(r)

    resolve_emergency(robot="GLOBAL")  # por si acaso

    return jsonify({
        "status": "emergency_resolved",
        "resolved": resolved
    })

@app.route("/reset", methods=["POST"])
def reset():
    """Reset del estado interno."""
    reset_state()
    return jsonify({"status": "reset_ok"})


# ============================================================
# 🧪 RUTA INTERNA QA — /internal/test-signal
# ============================================================
# EXCLUSIVA para pruebas controladas. NUNCA usar desde TradingView.
# Token independiente: INTERNAL_TEST_TOKEN (variable de entorno Render).
# Salta: timestamp expiry, anti-duplicados, schema TV estricto.
# NO salta: queue, signal_handler, state, trade_log, BD, BingX.
# demo=True forzado siempre — nunca ejecuta con dinero real.
# Logs marcados con [TEST] para distinguir de señales reales.
# ============================================================

@app.route("/internal/test-signal", methods=["POST"])
def internal_test_signal():
    from flask import request as freq
    from config.settings import INTERNAL_TEST_TOKEN
    from core.queue_manager import enqueue

    # ── Autenticación token interno ──────────────────────────
    if not INTERNAL_TEST_TOKEN:
        logger.error("🧪 [TEST] INTERNAL_TEST_TOKEN no configurado — ruta deshabilitada")
        return jsonify({"error": "Test route disabled — INTERNAL_TEST_TOKEN not set"}), 503

    auth_header = freq.headers.get("X-Internal-Token", "")
    if auth_header != INTERNAL_TEST_TOKEN:
        logger.warning("🧪 [TEST] Token interno inválido — acceso denegado")
        return jsonify({"error": "Unauthorized"}), 401

    # ── Parsear payload ──────────────────────────────────────
    payload = freq.get_json(silent=True, force=True)
    if not payload:
        return jsonify({"error": "Invalid JSON"}), 400

    # ── Campos mínimos obligatorios ──────────────────────────
    # Menos estricto que TV — no requiere time/tf reales
    required = ["signal", "symbol", "price", "robot"]
    missing  = [f for f in required if not payload.get(f)]
    if missing:
        return jsonify({
            "error":   "Missing required fields",
            "missing": missing
        }), 400

    # ── Inyectar campos de control ───────────────────────────
    # demo forzado — nunca ejecuta con dinero real desde esta ruta
    payload["_test_mode"] = True
    payload["user_id"]    = payload.get("user_id", "default")

    # tf y time opcionales — rellenar con defaults si no vienen
    if not payload.get("tf"):
        payload["tf"] = "TEST"
    if not payload.get("time"):
        payload["time"] = format_log_time()

    logger.info(
        f"🧪 [TEST] Señal interna encolada: "
        f"{payload.get('signal')} | {payload.get('symbol')} | "
        f"user={payload.get('user_id')} | robot={payload.get('robot')}"
    )

    enqueue(payload, user_id=payload["user_id"])

    return jsonify({
        "status":  "queued",
        "test":    True,
        "signal":  payload.get("signal"),
        "symbol":  payload.get("symbol"),
        "user_id": payload.get("user_id"),
    }), 200


# ============================================================
# 🔧 ARRANQUE
# ============================================================
if __name__ == "__main__":
    logger.info("=" * 50)
    logger.info("🚀 CAZADOR MIDDLEWARE ARRANCANDO")
    logger.info(f"🧪 DEMO MODE: {DEMO_MODE}")
    logger.info("=" * 50)

    # Validar configuración
    errors = validate()
    if errors and not DEMO_MODE:
        for e in errors:
            logger.error(f"❌ Config error: {e}")
        logger.warning("⚠️ Arrancando en modo demo por errores de config")

    # #12 — inicializar BD antes que nada
    from data.database import init_db
    init_db()

    # Cargar estado persistente
    load_state()

    # ── Limpiar SL broker order_ids zombies al arrancar ─────────
    try:
        from data.state import get_all_user_ids, _states, save_state
    
        for uid in get_all_user_ids():
            st = _states.get(uid, {})
            positions = st.get("positions", {})
    
            for sym, pos in positions.items():
                for side_key, side_name in [
                    ("sl_broker_order_id_long",  "LONG"),
                    ("sl_broker_order_id_short", "SHORT"),
                ]:
                    order_id = pos.get(side_key)
                    if not order_id:
                        continue
    
                    logger.info(
                        f"🧹 [{uid}] Cancelando SL {side_name} zombie "
                        f"al arrancar {sym} orderId={order_id}"
                    )
    
                    try:
                        cancel_result = cancel_order(
                            symbol=sym,
                            order_id=str(order_id),
                            robot="STARTUP"
                        )
                        code = cancel_result.get("code")
                        if code == 0:
                            logger.info(
                                f"✅ [{uid}] SL {side_name} zombie cancelado "
                                f"en BingX {sym}"
                            )
                        elif code == 109400:
                            logger.info(
                                f"ℹ️ [{uid}] SL {side_name} {sym} ya no existía "
                                f"en BingX — limpiando state"
                            )
                        else:
                            logger.warning(
                                f"⚠️ [{uid}] Cancel SL {side_name} {sym} "
                                f"code={code} — limpiando state igualmente"
                            )
                    except Exception as e:
                        logger.warning(
                            f"⚠️ [{uid}] Error cancelando SL {side_name} "
                            f"{sym}: {e} — limpiando state igualmente"
                        )
    
                    pos[side_key] = None
    
            save_state(uid)
    
        logger.info("✅ SL broker order_ids limpiados al arrancar")
    
    except Exception as e:
        logger.error(f"❌ Error limpiando SL zombies al arrancar: {e}")

    
    # Inicializar contadores BingX en 0 si no existen
    state = get_state()
    if "bingx_long_count" not in state:
        update_state({"bingx_long_count": 0, "bingx_short_count": 0})
    update_state({"started_at": format_log_time()})
    load_trades()
    preload_market()

    # ── Sincronizar pirámide con BingX al arrancar ──────────
    try:
        from data.state import update_state

        pos_data = get_positions()

        positions_list = [
            p for p in (pos_data.get("data") or [])
            if float(p.get("positionAmt", 0)) != 0
        ]

        long_count = sum(
            1 for p in positions_list
            if p.get("positionSide") == "LONG"
        )

        short_count = sum(
            1 for p in positions_list
            if p.get("positionSide") == "SHORT"
        )

        if long_count > 0 or short_count > 0:
            update_state({
                "pyramid_long_count":  long_count,
                "pyramid_short_count": short_count,
                "bingx_long_count":    long_count,
                "bingx_short_count":   short_count,
            })
            logger.info(
                f"📈 Pirámide sincronizada al arrancar — "
                f"LONG={long_count} SHORT={short_count}"
            )
        else:
            update_state({
                "bingx_long_count":  0,
                "bingx_short_count": 0,
            })
            logger.info(
                "📈 Sin posiciones abiertas al arrancar — "
                "pirámide en 0"
            )

    except Exception as e:
        logger.error(
            f"❌ Error sincronizando pirámide al arrancar: {e}"
        )

    # Arrancar workers
    from core.emergency import start_watchdog

    start_worker()
    start_reconciler()
    start_watchdog()

    logger.info("✅ Sistema listo")
    app.run(host="0.0.0.0", port=5000, debug=False)
