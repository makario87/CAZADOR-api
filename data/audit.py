"""
data/audit.py

Módulo de trazabilidad completa de eventos del sistema.
Escribe en la tabla audit_log de SQLite.

Eventos definidos:
    WEBHOOK_IN          — señal recibida del webhook
    SIGNAL_PROCESSED    — señal procesada por signal_handler
    ORDER_SENT          — orden enviada a BingX
    ORDER_FILLED        — orden confirmada por BingX
    SL_HIT              — stop loss ejecutado
    GIRO                — cambio de dirección long↔short
    EMERGENCY_ON        — emergency activado
    EMERGENCY_OFF       — emergency desactivado
    BINGX_ERROR         — error de comunicación con BingX
    RECONCILER_EVENT    — evento del reconciler
    USER_CREATED        — usuario creado en BD
    USER_UPDATED        — usuario modificado
    APIKEY_ADDED        — API key añadida (cifrada)
    APIKEY_REMOVED      — API key eliminada
    SYSTEM_START        — arranque del middleware
    SYSTEM_ERROR        — error crítico de sistema

Sesión 12 — módulo audit_log
"""
import json
from datetime import datetime, timezone
from data.database import db_execute, db_fetchall
from logs.logger import get_logger

logger = get_logger(__name__)

# ============================================================
# 📋 TIPOS DE EVENTO — constantes para evitar typos
# ============================================================

class AuditEvent:
    WEBHOOK_IN       = "WEBHOOK_IN"
    SIGNAL_PROCESSED = "SIGNAL_PROCESSED"
    ORDER_SENT       = "ORDER_SENT"
    ORDER_FILLED     = "ORDER_FILLED"
    SL_HIT           = "SL_HIT"
    GIRO             = "GIRO"
    EMERGENCY_ON     = "EMERGENCY_ON"
    EMERGENCY_OFF    = "EMERGENCY_OFF"
    BINGX_ERROR      = "BINGX_ERROR"
    RECONCILER_EVENT = "RECONCILER_EVENT"
    USER_CREATED     = "USER_CREATED"
    USER_UPDATED     = "USER_UPDATED"
    APIKEY_ADDED     = "APIKEY_ADDED"
    APIKEY_REMOVED   = "APIKEY_REMOVED"
    SYSTEM_START     = "SYSTEM_START"
    SYSTEM_ERROR     = "SYSTEM_ERROR"


# ============================================================
# ✍️ ESCRITURA
# ============================================================

def log_event(
    event_type: str,
    *,
    user_id:  str  = None,
    robot_id: str  = None,
    symbol:   str  = None,
    level:    str  = "INFO",
    detail:   dict = None,
    ip:       str  = None
) -> None:
    """
    Registra un evento en audit_log.
    Nunca lanza excepción — un fallo de auditoría no debe
    interrumpir la operación principal.
    """
    try:
        detail_json = json.dumps(detail, ensure_ascii=False) if detail else None
        db_execute(
            """
            INSERT INTO audit_log
                (timestamp, user_id, robot_id, symbol, event_type, level, detail, ip)
            VALUES
                (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f"),
                str(user_id)  if user_id  else None,
                str(robot_id) if robot_id else None,
                symbol,
                event_type,
                level,
                detail_json,
                ip,
            )
        )
    except Exception as e:
        # Log al archivo pero nunca propagar — auditoría es best-effort
        logger.error(f"❌ audit_log fallo escribiendo {event_type}: {e}")


# ============================================================
# 🔍 LECTURA — para el panel
# ============================================================

def get_recent_events(limit: int = 100, level: str = None, event_type: str = None) -> list:
    """
    Devuelve eventos recientes para el panel.
    Filtra opcionalmente por level y/o event_type.
    """
    conditions = []
    params     = []

    if level:
        conditions.append("level = ?")
        params.append(level)
    if event_type:
        conditions.append("event_type = ?")
        params.append(event_type)

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    params.append(limit)

    rows = db_fetchall(
        f"""
        SELECT * FROM audit_log
        {where}
        ORDER BY timestamp DESC
        LIMIT ?
        """,
        tuple(params)
    )
    return [dict(r) for r in rows]


def get_user_events(user_id: str, limit: int = 50) -> list:
    """Historial de eventos de un usuario concreto."""
    rows = db_fetchall(
        """
        SELECT * FROM audit_log
        WHERE user_id = ?
        ORDER BY timestamp DESC
        LIMIT ?
        """,
        (str(user_id), limit)
    )
    return [dict(r) for r in rows]


def get_error_events(limit: int = 50) -> list:
    """Errores y warnings recientes — para alertas del panel."""
    rows = db_fetchall(
        """
        SELECT * FROM audit_log
        WHERE level IN ('ERROR', 'WARN')
        ORDER BY timestamp DESC
        LIMIT ?
        """,
        (limit,)
    )
    return [dict(r) for r in rows]
