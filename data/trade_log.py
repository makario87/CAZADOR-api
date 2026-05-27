"""
data/trade_log.py

Registro persistente de todas las operaciones ejecutadas.
Sesión 7 — #12 BD real: migrado de CSV /tmp a SQLite.
Sesión 9 — #12d: user_id obligatorio en log_trade + propagado a consultas.

Interfaz pública sin cambios de firma excepto log_trade (añade user_id obligatorio):
  log_trade(), get_trades(), get_trades_by_symbol(),
  get_trades_by_signal(), get_summary(), export_csv_string(),
  clear_trades(), load_trades()
"""
import csv
import io
from utils.time_utils import format_log_time
from data.database import db_execute, db_fetchall
from logs.logger import get_logger

logger = get_logger(__name__)

# Mantenido por compatibilidad con csv_exporter y cualquier
# código que importe TRADE_FIELDS directamente
TRADE_FIELDS = [
    "timestamp",
    "robot",
    "symbol",
    "signal",
    "qty",
    "price",
    "result",
    "demo",
    "user_id",   # añadido sesión 9
]


# ============================================================
# 🔧 HELPER INTERNO
# ============================================================

def _side_from_signal(signal: str) -> str:
    """Infiere LONG/SHORT del nombre de señal para columna side."""
    s = signal.upper()
    if any(x in s for x in ("LONG", "BUY", "ENTRY_L")):
        return "LONG"
    if any(x in s for x in ("SHORT", "SELL", "ENTRY_S")):
        return "SHORT"
    return "UNKNOWN"


# ============================================================
# 💾 COMPATIBILIDAD ARRANQUE
# ============================================================

def load_trades():
    """
    Era necesario en la versión CSV para cargar /tmp al arrancar.
    Con SQLite los datos ya están en BD — no hace nada.
    Mantenido para no romper app.py.
    """
    count = db_fetchall("SELECT COUNT(*) as n FROM trades")[0]["n"]
    logger.info(f"✅ BD trades lista — {count} trades históricos")


# ============================================================
# 📝 REGISTRO DE TRADES
# ============================================================

def log_trade(
    signal:  str,
    symbol:  str,
    qty:     float,
    price:   str,
    result:  dict,
    user_id: str,          # OBLIGATORIO — sin default intencional
    robot:   str  = "CAZADOR",
    demo:    bool = True,
):
    """
    Registra una operación ejecutada en SQLite.

    user_id es obligatorio y posicional-por-nombre para que ninguna
    rama del caller pueda omitirlo silenciosamente.
    Si llega vacío o None se lanza ValueError — fallo ruidoso preferido
    a auditoría silenciosa con user_id nulo.
    """
    if not user_id:
        raise ValueError(
            f"log_trade llamado sin user_id — signal={signal} symbol={symbol}. "
            "Revisar propagación en signal_handler."
        )

    try:
        db_execute(
            """INSERT INTO trades
               (user_id, symbol, side, signal, qty, price, result, demo, timestamp)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                user_id,
                symbol,
                _side_from_signal(signal),
                signal,
                float(qty)   if qty   else None,
                float(price) if price else None,
                str(result),
                1 if demo else 0,
                format_log_time(),
            )
        )
        logger.info(
            f"📝 Trade registrado: {signal} | {symbol} | "
            f"qty={qty} | demo={demo} | user={user_id}"
        )
    except ValueError:
        raise   # re-lanza el ValueError de user_id vacío
    except Exception as e:
        logger.error(f"❌ Error registrando trade: {e}")


# ============================================================
# 📊 CONSULTAS
# ============================================================

def get_trades(user_id: str = None) -> list:
    """
    Retorna trades como lista de dicts.
    Si se pasa user_id filtra por ese usuario — recomendado.
    Sin user_id devuelve todos (uso interno / admin).
    """
    if user_id:
        rows = db_fetchall(
            "SELECT * FROM trades WHERE user_id=? ORDER BY id",
            (user_id,)
        )
    else:
        rows = db_fetchall("SELECT * FROM trades ORDER BY id")
    return [dict(r) for r in rows]


def get_trades_by_symbol(symbol: str, user_id: str = None) -> list:
    """Filtra trades por símbolo, opcionalmente también por usuario."""
    if user_id:
        rows = db_fetchall(
            "SELECT * FROM trades WHERE symbol=? AND user_id=? ORDER BY id",
            (symbol, user_id)
        )
    else:
        rows = db_fetchall(
            "SELECT * FROM trades WHERE symbol=? ORDER BY id",
            (symbol,)
        )
    return [dict(r) for r in rows]


def get_trades_by_signal(signal: str, user_id: str = None) -> list:
    """Filtra trades por tipo de señal, opcionalmente también por usuario."""
    if user_id:
        rows = db_fetchall(
            "SELECT * FROM trades WHERE signal=? AND user_id=? ORDER BY id",
            (signal, user_id)
        )
    else:
        rows = db_fetchall(
            "SELECT * FROM trades WHERE signal=? ORDER BY id",
            (signal,)
        )
    return [dict(r) for r in rows]


def get_summary(user_id: str = None) -> dict:
    """
    Resumen rápido del historial.
    Con user_id: resumen de ese usuario.
    Sin user_id: resumen global (admin).
    """
    trades = get_trades(user_id=user_id)
    return {
        "total_trades":  len(trades),
        "symbols":       list(set(t["symbol"] for t in trades)),
        "signals_seen":  list(set(t["signal"] for t in trades)),
        "last_trade":    trades[-1] if trades else None,
        "user_id":       user_id or "ALL",
    }


# ============================================================
# 📤 EXPORTACIÓN
# ============================================================

def export_csv_string(user_id: str = None) -> str:
    """
    Exporta trades como string CSV.
    Con user_id: solo ese usuario. Sin user_id: todos.
    """
    trades = get_trades(user_id=user_id)
    if not trades:
        return ""
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=TRADE_FIELDS)
    writer.writeheader()
    for t in trades:
        writer.writerow({k: t.get(k, "") for k in TRADE_FIELDS})
    return output.getvalue()


def clear_trades(user_id: str = None):
    """
    Limpia historial. Solo para debug.
    Con user_id: solo ese usuario. Sin user_id: tabla completa.
    """
    if user_id:
        db_execute("DELETE FROM trades WHERE user_id=?", (user_id,))
        logger.info(f"🗑️ Historial de trades limpiado — user={user_id}")
    else:
        db_execute("DELETE FROM trades")
        logger.info("🗑️ Historial de trades limpiado — TODOS los usuarios")
