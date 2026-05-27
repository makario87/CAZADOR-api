"""
data/database.py

Inicialización y acceso a SQLite.
Reemplaza /tmp JSON y CSV en producción.

Sesión 7 — #12 BD real
"""
import sqlite3
import os
import threading
from logs.logger import get_logger

logger = get_logger(__name__)

# ============================================================
# 📁 RUTA BD
# ============================================================
# /tmp sigue usándose HASTA que tengamos PostgreSQL (#12 fase 2)
# Pero SQLite sobrevive reinicios por sleep — solo muere en deploy
# Mismo trade-off que antes, pero estructura lista para Postgres
DB_PATH = os.getenv("DB_PATH", "/tmp/cazador.db")

_local = threading.local()   # conexión por hilo


def get_conn() -> sqlite3.Connection:
    """
    Devuelve conexión SQLite del hilo actual.
    Crea una nueva si no existe.
    row_factory = Row → acceso por nombre de columna.
    """
    if not hasattr(_local, "conn") or _local.conn is None:
        _local.conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        _local.conn.row_factory = sqlite3.Row
        _local.conn.execute("PRAGMA journal_mode=WAL")   # concurrencia lectores
        _local.conn.execute("PRAGMA foreign_keys=ON")
    return _local.conn


# ============================================================
# 🏗️ SCHEMA
# ============================================================

_SCHEMA = """

-- ── Robots / estrategias ─────────────────────────────────
CREATE TABLE IF NOT EXISTS robots (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL UNIQUE,      -- "CAZADOR"
    description TEXT,
    active      INTEGER NOT NULL DEFAULT 1
);

-- ── Usuarios ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS users (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    email       TEXT UNIQUE,
    telegram_id TEXT,
    active      INTEGER NOT NULL DEFAULT 1,
    plan        TEXT    NOT NULL DEFAULT 'free',   -- free | pro | enterprise
    env         TEXT    NOT NULL DEFAULT 'demo'    -- demo | live
);

-- ── API keys cifradas ─────────────────────────────────────
CREATE TABLE IF NOT EXISTS api_keys (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id          INTEGER NOT NULL REFERENCES users(id),
    exchange         TEXT    NOT NULL DEFAULT 'bingx',
    key_encrypted    TEXT    NOT NULL,
    secret_encrypted TEXT    NOT NULL,
    env              TEXT    NOT NULL DEFAULT 'demo',   -- demo | live
    active           INTEGER NOT NULL DEFAULT 1,
    created_at       TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- ── Suscripciones usuario↔robot ───────────────────────────
CREATE TABLE IF NOT EXISTS subscriptions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id),
    robot_id    INTEGER NOT NULL REFERENCES robots(id),
    active      INTEGER NOT NULL DEFAULT 1,
    risk_pct    REAL    NOT NULL DEFAULT 0.01,
    leverage    INTEGER NOT NULL DEFAULT 10,
    capital_pct REAL    NOT NULL DEFAULT 1.0,
    proxy_id    INTEGER REFERENCES proxies(id)
);

-- ── Configuración por usuario+robot+símbolo ───────────────
CREATE TABLE IF NOT EXISTS configs (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users(id),
    robot_id   INTEGER NOT NULL REFERENCES robots(id),
    symbol     TEXT    NOT NULL,
    params     TEXT    NOT NULL DEFAULT '{}',   -- JSON
    updated_at TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- ── Historial de trades ───────────────────────────────────
CREATE TABLE IF NOT EXISTS trades (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER REFERENCES users(id),
    robot_id   INTEGER REFERENCES robots(id),
    symbol     TEXT    NOT NULL,
    side       TEXT    NOT NULL,   -- LONG | SHORT
    signal     TEXT    NOT NULL,
    qty        REAL,
    price      REAL,
    pnl        REAL,
    demo       INTEGER NOT NULL DEFAULT 1,
    result     TEXT,               -- JSON raw de BingX
    timestamp  TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- ── Estado del sistema (reemplaza JSON en /tmp) ───────────
CREATE TABLE IF NOT EXISTS system_state (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ── Proxies ───────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS proxies (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER REFERENCES users(id),
    ip      TEXT NOT NULL,
    port    INTEGER NOT NULL,
    active  INTEGER NOT NULL DEFAULT 1
);

"""


def init_db():
    """
    Crea todas las tablas si no existen.
    Idempotente — seguro llamar en cada arranque.
    """
    try:
        conn = get_conn()
        conn.executescript(_SCHEMA)
        conn.commit()
        logger.info(f"✅ BD inicializada: {DB_PATH}")
    except Exception as e:
        logger.error(f"❌ Error inicializando BD: {e}")
        raise


# ============================================================
# 🔧 HELPERS GENÉRICOS
# ============================================================

def db_execute(sql: str, params: tuple = ()) -> sqlite3.Cursor:
    """Ejecuta INSERT/UPDATE/DELETE. Hace commit automático."""
    conn = get_conn()
    cur  = conn.execute(sql, params)
    conn.commit()
    return cur


def db_fetchone(sql: str, params: tuple = ()):
    """SELECT que devuelve una fila (sqlite3.Row) o None."""
    return get_conn().execute(sql, params).fetchone()


def db_fetchall(sql: str, params: tuple = ()):
    """SELECT que devuelve lista de sqlite3.Row."""
    return get_conn().execute(sql, params).fetchall()
