"""
core/emergency.py
Sistema de emergencia.
Si algo falla, bloquea nuevas órdenes y registra el error.
TODO: añadir notificaciones (email/Telegram).
"""
from data.state import update_state
from logs.logger import get_logger

logger = get_logger(__name__)

def trigger_emergency(reason: str):
    """Activa modo emergencia — bloquea todas las nuevas órdenes."""
    logger.error(f"🚨 EMERGENCIA ACTIVADA: {reason}")
    update_state({
        "emergency": True,
        "emergency_reason": reason,
        "blocked": True
    })

def resolve_emergency():
    """Desactiva modo emergencia manualmente desde el panel."""
    logger.info("✅ Emergencia resuelta manualmente")
    update_state({
        "emergency": False,
        "emergency_reason": None,
        "blocked": False
    })

def is_emergency() -> bool:
    from data.state import get_state
    return get_state().get("emergency", False)
