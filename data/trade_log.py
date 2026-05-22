"""
data/trade_log.py

Registro persistente de todas las operaciones ejecutadas.
Guarda en RAM + CSV en disco inmediatamente tras cada trade.

LIMITACIÓN CONOCIDA:
/tmp se borra con cada deploy nuevo.
Suficiente para reinicios por inactividad.
En el futuro esto se reemplaza por SQLite/PostgreSQL
sin cambiar log_trade() ni el resto del código.
"""
import csv
import io
import os
import threading
from utils.time_utils import format_log_time
from logs.logger import get_logger

logger = get_logger(__name__)

# ============================================================
# 📁 ARCHIVO DE PERSISTENCIA
# ============================================================
TRADES_FILE = "/tmp/cazador_trades.csv"

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

_lock   = threading.Lock()
_trades = []

# ============================================================
# 💾 PERSISTENCIA
# ============================================================

def load_trades():
    """
    Carga trades previos desde CSV al arrancar.
    Si no existe el archivo arranca desde cero.
    """
    global _trades
    if not os.path.exists(TRADES_FILE):
        logger.info("📂 No hay trades previos — historial desde cero")
        return

    try:
        with open(TRADES_FILE, "r") as f:
            reader = csv.DictReader(f)
            loaded = list(reader)
            with _lock:
                _trades = loaded
        logger.info(f"✅ {len(_trades)} trades restaurados desde disco")
    except Exception as e:
        logger.error(f"❌ Error cargando trades: {e}")

def _append_to_csv(trade: dict):
    """Añade una línea al CSV en disco inmediatamente."""
    try:
        file_exists = os.path.exists(TRADES_FILE)
        with open(TRADES_FILE, "a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=TRADE_FIELDS)
            if not file_exists:
                writer.writeheader()
            writer.writerow({k: trade.get(k, "") for k in TRADE_FIELDS})
    except Exception as e:
        logger.error(f"❌ Error escribiendo trade al CSV: {e}")

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
    Registra una operación ejecutada.
    Guarda en RAM y persiste al CSV inmediatamente.
    """
    trade = {
        "timestamp": format_log_time(),
        "robot":     robot,
        "symbol":    symbol,
        "signal":    signal,
        "qty":       str(qty),
        "price":     str(price),
        "result":    str(result),
        "demo":      str(demo),
    }

    with _lock:
        _trades.append(trade)

    _append_to_csv(trade)
    logger.info(f"📝 Trade registrado: {signal} | {symbol} | qty={qty} | demo={demo}")

# ============================================================
# 📊 CONSULTAS
# ============================================================

def get_trades() -> list:
    """Retorna copia del historial completo."""
    with _lock:
        return _trades.copy()

def get_trades_by_symbol(symbol: str) -> list:
    """Filtra trades por símbolo."""
    with _lock:
        return [t for t in _trades if t.get("symbol") == symbol]

def get_trades_by_signal(signal: str) -> list:
    """Filtra trades por tipo de señal."""
    with _lock:
        return [t for t in _trades if t.get("signal") == signal]

def get_summary() -> dict:
    """Resumen rápido del historial."""
    with _lock:
        total    = len(_trades)
        symbols  = list(set(t.get("symbol", "") for t in _trades))
        signals  = list(set(t.get("signal", "") for t in _trades))
        last     = _trades[-1] if _trades else None

    return {
        "total_trades":  total,
        "symbols":       symbols,
        "signals_seen":  signals,
        "last_trade":    last,
    }

# ============================================================
# 📤 EXPORTACIÓN
# ============================================================

def export_csv_string() -> str:
    """Exporta todos los trades como string CSV."""
    trades = get_trades()
    if not trades:
        return ""

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=TRADE_FIELDS)
    writer.writeheader()
    writer.writerows(trades)
    return output.getvalue()

def clear_trades():
    """Limpia historial en RAM y disco. Solo para debug."""
    with _lock:
        _trades.clear()
    if os.path.exists(TRADES_FILE):
        os.remove(TRADES_FILE)
    logger.info("🗑️ Historial de trades limpiado")
