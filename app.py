"""
app.py
Arranque principal del sistema CAZADOR → Python → BingX.
"""
from flask import Flask, jsonify
from config.settings import DEMO_MODE, validate
from routes.webhook import webhook_bp
from core.queue_manager import start_worker
from core.reconciler import start_reconciler
from core.emergency import resolve_emergency, is_emergency
from data.state import get_state, reset_state
from data.trade_log import get_trades
from reports.csv_exporter import export_csv
from brokers.bingx import get_balance, get_positions
from logs.logger import get_logger

logger = get_logger(__name__)

# ============================================================
# 🚀 CREAR APP FLASK
# ============================================================
app = Flask(__name__)
app.register_blueprint(webhook_bp)

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

@app.route("/ping", methods=["GET"])
def ping():
    """Mantiene vivo el servidor en Render free tier."""
    return jsonify({"status": "pong"}), 200

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
    """Historial de operaciones."""
    return jsonify(get_trades())

@app.route("/trades/csv", methods=["GET"])
def trades_csv():
    """Exporta operaciones a CSV."""
    from flask import Response
    csv_data = export_csv()
    return Response(csv_data, mimetype="text/csv",
                    headers={"Content-Disposition": "attachment;filename=trades.csv"})

@app.route("/emergency/resolve", methods=["POST"])
def emergency_resolve():
    """Resuelve la emergencia manualmente desde el panel."""
    resolve_emergency()
    return jsonify({"status": "emergency_resolved"})

@app.route("/reset", methods=["POST"])
def reset():
    """Reset del estado interno."""
    reset_state()
    return jsonify({"status": "reset_ok"})

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

    # Arrancar workers
    start_worker()
    start_reconciler()

    logger.info("✅ Sistema listo")
    app.run(host="0.0.0.0", port=5000, debug=False)
