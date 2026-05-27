"""
core/emergency.py
Sistema de emergencia.
Si algo falla, bloquea nuevas órdenes y registra el error.
TODO: añadir notificaciones (email/Telegram).
"""
import threading
import time

from data.state import set_robot_emergency, get_robot_emergency, is_any_emergency
from logs.logger import get_logger

logger = get_logger(__name__)

def trigger_emergency(reason: str, robot: str = "GLOBAL"):
    """
    Activa emergency para un robot específico.
    robot="GLOBAL" para emergencias de infraestructura (watchdog).
    """
    logger.critical(f"🚨 EMERGENCY ACTIVADA | robot={robot} | motivo={reason}")
    set_robot_emergency(robot=robot, active=True, reason=reason)


def activate_emergency(robot: str, reason: str):
    """Alias explícito usado desde webhook.py."""
    trigger_emergency(reason=reason, robot=robot)


def resolve_emergency(robot: str = "GLOBAL"):
    """
    Desactiva emergency para un robot específico.
    """
    logger.info(f"✅ Emergency resuelta manualmente | robot={robot}")
    set_robot_emergency(robot=robot, active=False, reason="")


def is_emergency(robot: str = None) -> bool:
    """
    Sin args → True si cualquier robot está en emergency.
    Con robot= → True solo si ese robot está en emergency.
    """
    if robot is None:
        return is_any_emergency()
    return get_robot_emergency(robot).get("active", False)


def get_emergency_reason(robot: str = "GLOBAL") -> str:
    return get_robot_emergency(robot).get("reason", "")

# ============================================================
# 🐕 WATCHDOG — #5
# ============================================================

_WATCHDOG_INTERVAL      = 60
_WATCHDOG_MAX_FAILURES  = 3

_watchdog_thread   = None
_consecutive_fails = 0


def start_watchdog():
    """Arranca el hilo watchdog."""
    global _watchdog_thread

    if _watchdog_thread and _watchdog_thread.is_alive():
        return

    _watchdog_thread = threading.Thread(
        target=_watchdog_loop,
        daemon=True
    )

    _watchdog_thread.start()

    logger.info(
        f"🐕 Watchdog BingX arrancado "
        f"(cada {_WATCHDOG_INTERVAL}s, "
        f"max_fails={_WATCHDOG_MAX_FAILURES})"
    )


def _watchdog_loop():
    global _consecutive_fails

    while True:
        try:
            time.sleep(_WATCHDOG_INTERVAL)
            _check_bingx_connection()

        except Exception as e:
            logger.error(f"❌ Error en watchdog loop: {e}")


def _check_bingx_connection():
    global _consecutive_fails

    from brokers.bingx import ping_bingx

    ok = ping_bingx()

    if ok:

        if _consecutive_fails > 0:
            logger.info(
                f"✅ Watchdog — BingX recuperado "
                f"tras {_consecutive_fails} fallo(s)"
            )

        _consecutive_fails = 0
        return

    _consecutive_fails += 1

    logger.warning(
        f"⚠️ Watchdog — BingX no responde "
        f"(fallo {_consecutive_fails}/"
        f"{_WATCHDOG_MAX_FAILURES})"
    )

    if _consecutive_fails >= _WATCHDOG_MAX_FAILURES:

        if not is_emergency():

            trigger_emergency(
                f"Watchdog: BingX sin respuesta "
                f"{_consecutive_fails} veces consecutivas"
            )

        _consecutive_fails = 0

def is_watchdog_alive() -> bool:
    return _watchdog_thread is not None and _watchdog_thread.is_alive()

def get_consecutive_fails() -> int:
    return _consecutive_fails
