"""
utils/auth.py
Validación del token secreto del webhook.
TradingView debe mandar el token en el header: X-Webhook-Token
"""
import hmac
import hashlib
from config.settings import WEBHOOK_SECRET_TOKEN
from logs.logger import get_logger

logger = get_logger(__name__)

def validate_webhook_token(request) -> bool:
    """
    Valida que la petición viene de TradingView con el token correcto.
    El token debe venir en el header: X-Webhook-Token
    """
    token = request.headers.get("X-Webhook-Token", "")

    if not token:
        logger.warning("⚠️ Webhook recibido sin token de autenticación")
        return False

    # Comparación segura anti timing-attack
    valid = hmac.compare_digest(token.strip(), WEBHOOK_SECRET_TOKEN.strip())

    if not valid:
        logger.warning("🚨 Token de webhook inválido — posible intento no autorizado")

    return valid
