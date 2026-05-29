"""
data/users.py

Módulo de gestión de usuarios en BD.
CRUD completo con auditoría integrada en cada operación.

Sesión 12 — módulo usuarios
"""
from data.database import db_execute, db_fetchone, db_fetchall
from data.audit import log_event, AuditEvent
from logs.logger import get_logger

logger = get_logger(__name__)


# ============================================================
# ✍️ CREAR USUARIO
# ============================================================

def create_user(
    name:        str,
    email:       str  = None,
    telegram_id: str  = None,
    plan:        str  = "free",
    env:         str  = "demo"
) -> int:
    """
    Crea un usuario nuevo en BD.
    Devuelve el id generado.
    Lanza ValueError si el email ya existe.
    """
    if email:
        existing = db_fetchone("SELECT id FROM users WHERE email = ?", (email,))
        if existing:
            raise ValueError(f"Email ya registrado: {email}")

    cur = db_execute(
        """
        INSERT INTO users (name, email, telegram_id, plan, env, active)
        VALUES (?, ?, ?, ?, ?, 1)
        """,
        (name, email, telegram_id, plan, env)
    )
    user_id = cur.lastrowid
    logger.info(f"✅ Usuario creado: id={user_id} name={name} env={env}")

    log_event(
        AuditEvent.USER_CREATED,
        user_id=user_id,
        level="INFO",
        detail={"name": name, "email": email, "plan": plan, "env": env}
    )
    return user_id


# ============================================================
# 🔍 CONSULTAS
# ============================================================

def get_user(user_id: int) -> dict | None:
    """Devuelve un usuario por id o None si no existe."""
    row = db_fetchone("SELECT * FROM users WHERE id = ?", (user_id,))
    return dict(row) if row else None


def get_user_by_email(email: str) -> dict | None:
    """Devuelve un usuario por email o None si no existe."""
    row = db_fetchone("SELECT * FROM users WHERE email = ?", (email,))
    return dict(row) if row else None


def get_all_users(active_only: bool = True) -> list:
    """
    Devuelve lista de todos los usuarios.
    active_only=True filtra solo usuarios activos.
    """
    if active_only:
        rows = db_fetchall("SELECT * FROM users WHERE active = 1 ORDER BY id")
    else:
        rows = db_fetchall("SELECT * FROM users ORDER BY id")
    return [dict(r) for r in rows]


# ============================================================
# ✏️ ACTUALIZAR USUARIO
# ============================================================

def update_user(user_id: int, **kwargs) -> bool:
    """
    Actualiza campos de un usuario.
    Solo actualiza los campos pasados como kwargs.
    Campos permitidos: name, email, telegram_id, plan, env, active.
    Devuelve True si se actualizó, False si no existe.
    """
    allowed = {"name", "email", "telegram_id", "plan", "env", "active"}
    fields  = {k: v for k, v in kwargs.items() if k in allowed}

    if not fields:
        raise ValueError("No hay campos válidos para actualizar.")

    # Verificar que existe
    if not get_user(user_id):
        return False

    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values     = list(fields.values()) + [user_id]

    db_execute(f"UPDATE users SET {set_clause} WHERE id = ?", tuple(values))
    logger.info(f"✅ Usuario actualizado: id={user_id} campos={list(fields.keys())}")

    log_event(
        AuditEvent.USER_UPDATED,
        user_id=user_id,
        level="INFO",
        detail={"updated_fields": list(fields.keys())}
    )
    return True


# ============================================================
# 🗑️ DESACTIVAR USUARIO (soft delete)
# ============================================================

def deactivate_user(user_id: int) -> bool:
    """
    Desactiva un usuario (active=0).
    Nunca borra físicamente — soft delete siempre.
    """
    return update_user(user_id, active=0)


# ============================================================
# 🔎 RESUMEN PARA PANEL
# ============================================================

def get_users_summary() -> dict:
    """
    Resumen de usuarios para el panel.
    """
    total  = db_fetchone("SELECT COUNT(*) as n FROM users")
    active = db_fetchone("SELECT COUNT(*) as n FROM users WHERE active = 1")
    demo   = db_fetchone("SELECT COUNT(*) as n FROM users WHERE env = 'demo' AND active = 1")
    live   = db_fetchone("SELECT COUNT(*) as n FROM users WHERE env = 'live' AND active = 1")

    return {
        "total":       total["n"]  if total  else 0,
        "active":      active["n"] if active else 0,
        "demo":        demo["n"]   if demo   else 0,
        "live":        live["n"]   if live   else 0,
    }
