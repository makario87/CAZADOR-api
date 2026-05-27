"""
data/trade_log.py

Registro persistente de todas las operaciones ejecutadas.
Sesión 7 — #12 BD real: migrado de CSV /tmp a SQLite.

Interfaz pública sin cambios:
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
    robot:   str  = "CAZADOR",
    demo:    bool = True,
):
    """
    Registra una operación ejecutada en SQLite.
    Misma firma que la versión CSV — sin cambios para signal_handler.
    """
    try:
        db_execute(
            """INSERT INTO trades
               (symbol, side, signal, qty, price, result, demo, timestamp)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
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
            f"qty={qty} | demo={demo}"
        )
    except Exception as e:
        logger.error(f"❌ Error registrando trade: {e}")


# ============================================================
# 📊 CONSULTAS
# ============================================================

def get_trades() -> list:
    """Retorna todos los trades como lista de dicts."""
    rows = db_fetchall("SELECT * FROM trades ORDER BY id")
    return [dict(r) for r in rows]


def get_trades_by_symbol(symbol: str) -> list:
    """Filtra trades por símbolo."""
    rows = db_fetchall(
        "SELECT * FROM trades WHERE symbol=? ORDER BY id",
        (symbol,)
    )
    return [dict(r) for r in rows]


def get_trades_by_signal(signal: str) -> list:
    """Filtra trades por tipo de señal."""
    rows = db_fetchall(
        "SELECT * FROM trades WHERE signal=? ORDER BY id",
        (signal,)
    )
    return [dict(r) for r in rows]


def get_summary() -> dict:
    """Resumen rápido del historial."""
    rows   = db_fetchall("SELECT * FROM trades ORDER BY id")
    trades = [dict(r) for r in rows]
    return {
        "total_trades":  len(trades),
        "symbols":       list(set(t["symbol"] for t in trades)),
        "signals_seen":  list(set(t["signal"] for t in trades)),
        "last_trade":    trades[-1] if trades else None,
    }


# ============================================================
# 📤 EXPORTACIÓN
# ============================================================

def export_csv_string() -> str:
    """Exporta todos los trades como string CSV. Misma firma que antes."""
    trades = get_trades()
    if not trades:
        return ""
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=TRADE_FIELDS)
    writer.writeheader()
    for t in trades:
        writer.writerow({k: t.get(k, "") for k in TRADE_FIELDS})
    return output.getvalue()


def clear_trades():
    """Limpia historial completo. Solo para debug."""
    db_execute("DELETE FROM trades")
    logger.info("🗑️ Historial de trades limpiado")
