"""
routes/webhook.py
"""
from flask import Blueprint, request, jsonify
from utils.auth import validate_webhook_token
from utils.time_utils import is_signal_expired
from core.queue_manager import enqueue, queue_size
from logs.logger import get_logger
from data.state import record_webhook

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
        record_webhook("INVALID_JSON", ok=False)
        return jsonify({"error": "Invalid JSON"}), 400

    # Validar token
    if not validate_webhook_token(request, payload):
        record_webhook("UNAUTHORIZED", ok=False)
        return jsonify({"error": "Unauthorized"}), 401
        
    signal = payload.get("signal", "UNKNOWN")

    if "signal" not in payload:
        record_webhook("MISSING_SIGNAL", ok=False)
        return jsonify({"error": "Missing signal"}), 400

    if is_signal_expired(payload.get("time", "")):
        logger.warning(
            f"⏰ Señal EXPIRADA y descartada: "
            f"{signal} | "
            f"symbol={payload.get('symbol')} | "
            f"tv_time={payload.get('time')}"
        )
    
        record_webhook(signal + "_EXPIRED", ok=False)
    
        return jsonify({"status": "expired"}), 200

    record_webhook(signal, ok=True)

    enqueue(payload)
    
    logger.info(f"✅ Señal aceptada: {signal} | {payload.get('symbol')}")
    
    return jsonify({"status": "queued"}), 200
