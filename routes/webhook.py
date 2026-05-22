"""
routes/webhook.py
Endpoint que recibe señales de TradingView.
Valida token → encola señal → responde 200 rápido.
"""
from flask import Blueprint, request, jsonify
from utils.auth import validate_webhook_token
from utils.time_utils import is_signal_expired
from core.queue_manager import enqueue
from logs.logger import get_logger

logger = get_logger(__name__)

webhook_bp = Blueprint("webhook", __name__)

@webhook_bp.route("/webhook", methods=["POST"])
def receive_signal():
    """Recibe señal de TradingView."""

    # 1. Validar token
    if not validate_webhook_token(request):
        return jsonify({"error": "Unauthorized"}), 401

    # 2. Parsear JSON
    payload = request.get_json(silent=True)
    if not payload:
        logger.warning("⚠️ Webhook sin payload JSON")
        return jsonify({"error": "Invalid JSON"}), 400

    # 3. Verificar campos mínimos
    if "signal" not in payload:
        logger.warning(f"⚠️ Payload sin campo signal: {payload}")
        return jsonify({"error": "Missing signal"}), 400

    # 4. Verificar expiración de señal
    if is_signal_expired(payload.get("time", "")):
        logger.warning(f"⏰ Señal expirada ignorada: {payload.get('signal')}")
        return jsonify({"status": "expired"}), 200

    # 5. Encolar señal para procesar
    enqueue(payload)
    logger.info(f"✅ Señal aceptada: {payload.get('signal')} | {payload.get('symbol')}")

    # 6. Responder rápido (TradingView tiene timeout corto)
    return jsonify({"status": "queued"}), 200
