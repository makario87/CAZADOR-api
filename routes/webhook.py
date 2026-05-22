"""
routes/webhook.py
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

    # 🔍 DEBUG — log raw completo
    raw_body = request.get_data(as_text=True)
    logger.info(f"📦 RAW BODY: {raw_body}")
    logger.info(f"📋 HEADERS: {dict(request.headers)}")

    # Parsear JSON
    payload = request.get_json(silent=True, force=True)
    logger.info(f"🔍 JSON PARSED: {payload}")

    if not payload:
        logger.warning("⚠️ No se pudo parsear JSON")
        return jsonify({"error": "Invalid JSON"}), 400

    # Validar token
    if not validate_webhook_token(request, payload):
        return jsonify({"error": "Unauthorized"}), 401

    if "signal" not in payload:
        return jsonify({"error": "Missing signal"}), 400

    if is_signal_expired(payload.get("time", "")):
        return jsonify({"status": "expired"}), 200

    enqueue(payload)
    return jsonify({"status": "queued"}), 200
