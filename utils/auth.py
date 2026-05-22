"""
utils/auth.py
"""
import hmac
from config.settings import WEBHOOK_SECRET_TOKEN
from logs.logger import get_logger

logger = get_logger(__name__)

def validate_webhook_token(request, payload: dict = None) -> bool:
    """
    Busca el token en dos sitios:
    1. Header: X-Webhook-Token
    2. Body JSON: campo "token"
    """

    # Opción 1 — header
    token = request.headers.get("X-Webhook-Token", "").strip()

    # Opción 2 — body JSON
    if not token and payload:
        token = payload.get("token", "").strip()

    if not token:
        logger.warning("⚠️ Webhook recibido sin token")
        logger.warning(f"⚠️ Headers disponibles: {list(request.headers.keys())}")
        logger.warning(f"⚠️ Payload recibido: {payload}")
        return False

    valid = hmac.compare_digest(token, WEBHOOK_SECRET_TOKEN.strip())

    if not valid:
        logger.warning(f"🚨 Token inválido recibido: {token[:8]}...")

    return valid
