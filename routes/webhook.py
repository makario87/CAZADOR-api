"""
routes/webhook.py
"""
from flask import Blueprint, request, jsonify
from utils.auth import validate_webhook_token
from utils.time_utils import is_signal_expired
from core.queue_manager import enqueue
from core.emergency import activate_emergency
from logs.logger import get_logger
from data.state import record_webhook
from utils.security import validate_schema, validate_no_duplicate

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

    # ── Capa 3 — Schema validation ─────────────────────────────
    ok, motivo = validate_schema(payload)
    
    if not ok:
        robot = payload.get("robot", "UNKNOWN")
    
        logger.critical(
            f"🚨 SCHEMA INVÁLIDO — robot={robot} | {motivo}"
        )
    
        record_webhook(
            f"SCHEMA_FAIL:{motivo[:40]}",
            ok=False
        )
    
        _trigger_emergency(
            robot,
            f"schema_invalido:{motivo}"
        )
    
        return jsonify({
            "error": "Bad Request",
            "reason": motivo
        }), 400
        
    signal = payload.get("signal", "UNKNOWN")
    latency = None

    try:
        from datetime import datetime, timezone
    
        tv_time_str = payload.get("time", "")
    
        if tv_time_str:
    
            tv_time = datetime.fromisoformat(
                tv_time_str.replace("Z", "+00:00")
            )
    
            now_utc = datetime.now(timezone.utc)
    
            latency = round(
                (now_utc - tv_time).total_seconds(),
                2
            )
    
            logger.info(
                f"📡 TV→Render latency={latency}s | "
                f"signal={signal} | "
                f"symbol={payload.get('symbol')}"
            )
    
    except Exception as e:
    
        logger.debug(
            f"⚠️ No se pudo calcular latencia: {e}"
        )

    if "signal" not in payload:
        record_webhook("MISSING_SIGNAL", ok=False)
        return jsonify({"error": "Missing signal"}), 400

    if is_signal_expired(payload.get("time", "")):
        logger.warning(
            f"⏰ Señal EXPIRADA y descartada: "
            f"{signal} | "
            f"symbol={payload.get('symbol')} | "
            f"tv_time={payload.get('time')} | "
            f"latency={latency}s"
        )
    
        record_webhook(signal + "_EXPIRED", ok=False)
    
        return jsonify({"status": "expired"}), 200
        
    # ── Capa 5 — Anti-duplicados ──────────────────────────
    # NO activa emergency — puede ser retry legítimo.
    ok, motivo = validate_no_duplicate(payload)

    if not ok:
        logger.warning(
            f"⚠️ DUPLICADO descartado | "
            f"{payload.get('robot')} | {motivo}"
        )

        record_webhook(
            f"DUPLICATE:{motivo[:40]}",
            ok=False
        )

        return jsonify({"error": "Duplicate signal"}), 409
        
    # Asignar user_id — hoy siempre "default", futuro: lookup en BD por token/robot
    payload["user_id"] = payload.get("user_id", "default")
    record_webhook(signal, ok=True)
    enqueue(payload, user_id=payload["user_id"])
    
    logger.info(f"✅ Señal aceptada: {signal} | {payload.get('symbol')}")
    
    return jsonify({"status": "queued"}), 200


def _trigger_emergency(robot: str, motivo: str) -> None:
    """
    Activa Emergency Mode para el robot afectado.
    """
    try:

        logger.critical(
            f"🚨 EMERGENCY MODE | "
            f"robot={robot} | motivo={motivo}"
        )

        activate_emergency(
            robot=robot,
            reason=f"SECURITY:{motivo}"
        )

    except Exception as e:

        logger.critical(
            f"🚨 EMERGENCY FALLÓ | "
            f"robot={robot} | "
            f"error={e}"
        )
