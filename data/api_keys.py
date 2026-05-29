"""
data/api_keys.py

Gestión de API keys cifradas en BD.
Las keys NUNCA se almacenan en texto plano.
Cifrado AES-256-GCM via utils/crypto.py.

Sesión 12 — módulo API keys cifradas
"""
from data.database import db_execute, db_fetchone, db_fetchall
from data.audit    import log_event, AuditEvent
from utils.crypto  import encrypt, decrypt, mask
from logs.logger   import get_logger

logger = get_logger(__name__)


# ============================================================
# ✍️ AÑADIR API KEY
# ============================================================

def add_api_key(
    user_id:  int,
    key:      str,
    secret:   str,
    exchange: str = "bingx",
    env:      str = "demo"
) -> int:
    """
    Cifra y almacena una API key en BD.
    Devuelve el id generado.
    Nunca almacena key ni secret en texto plano.
    """
    key_enc    = encrypt(key)
    secret_enc = encrypt(secret)

    cur = db_execute(
        """
        INSERT INTO api_keys
            (user_id, exchange, key_encrypted, secret_encrypted, env, active)
        VALUES (?, ?, ?, ?, ?, 1)
        """,
        (user_id, exchange, key_enc, secret_enc, env)
    )
    api_key_id = cur.lastrowid
    logger.info(
        f"✅ API key añadida: id={api_key_id} user={user_id} "
        f"exchange={exchange} env={env} key={mask(key)}"
    )

    log_event(
        AuditEvent.APIKEY_ADDED,
        user_id=user_id,
        level="INFO",
        detail={
            "api_key_id": api_key_id,
            "exchange":   exchange,
            "env":        env,
            "key_masked": mask(key)
            # secret nunca en audit_log ni en logs
        }
    )
    return api_key_id


# ============================================================
# 🔍 OBTENER API KEY DESCIFRADA
# ============================================================

def get_api_key(user_id: int, exchange: str = "bingx", env: str = "demo") -> dict | None:
    """
    Devuelve la API key activa de un usuario descifrada.
    Devuelve None si no existe.
    USO EXCLUSIVO del broker layer — nunca exponer al panel.
    """
    row = db_fetchone(
        """
        SELECT * FROM api_keys
        WHERE user_id = ? AND exchange = ? AND env = ? AND active = 1
        ORDER BY id DESC
        LIMIT 1
        """,
        (user_id, exchange, env)
    )
    if not row:
        return None

    return {
        "id":       row["id"],
        "user_id":  row["user_id"],
        "exchange": row["exchange"],
        "env":      row["env"],
        "key":      decrypt(row["key_encrypted"]),
        "secret":   decrypt(row["secret_encrypted"]),
    }


# ============================================================
# 🔍 LISTAR API KEYS (sin descifrar — para el panel)
# ============================================================

def list_api_keys(user_id: int) -> list:
    """
    Lista las API keys de un usuario SIN descifrar.
    Solo devuelve metadatos — nunca key ni secret.
    Seguro para mostrar en el panel.
    """
    rows = db_fetchall(
        """
        SELECT id, user_id, exchange, env, active, created_at
        FROM api_keys
        WHERE user_id = ?
        ORDER BY id DESC
        """,
        (user_id,)
    )
    return [dict(r) for r in rows]


# ============================================================
# 🗑️ DESACTIVAR API KEY (soft delete)
# ============================================================

def deactivate_api_key(api_key_id: int, user_id: int) -> bool:
    """
    Desactiva una API key (active=0).
    Requiere user_id para evitar que un usuario toque keys de otro.
    Nunca borra físicamente.
    """
    row = db_fetchone(
        "SELECT id FROM api_keys WHERE id = ? AND user_id = ? AND active = 1",
        (api_key_id, user_id)
    )
    if not row:
        return False

    db_execute(
        "UPDATE api_keys SET active = 0 WHERE id = ?",
        (api_key_id,)
    )
    logger.info(f"✅ API key desactivada: id={api_key_id} user={user_id}")

    log_event(
        AuditEvent.APIKEY_REMOVED,
        user_id=user_id,
        level="INFO",
        detail={"api_key_id": api_key_id}
    )
    return True


# ============================================================
# ✅ VERIFICAR QUE UNA KEY EXISTE Y ESTÁ ACTIVA
# ============================================================

def has_active_api_key(user_id: int, exchange: str = "bingx", env: str = "demo") -> bool:
    """
    Comprueba si un usuario tiene API key activa.
    Útil para validaciones antes de procesar señales.
    """
    row = db_fetchone(
        """
        SELECT id FROM api_keys
        WHERE user_id = ? AND exchange = ? AND env = ? AND active = 1
        LIMIT 1
        """,
        (user_id, exchange, env)
    )
    return row is not None
