"""
data/trade_log.py
Registro de todas las operaciones ejecutadas.
TODO: conectar con csv_exporter para exportar a CSV/Excel.
"""
import threading
from utils.time_utils import format_log_time
from logs.logger import get_logger

logger = get_logger(__name__)

_lock  = threading.Lock()
_trades = []

def log_trade(signal: str, symbol: str, qty: float, price: str, result: dict):
    """Registra una operación ejecutada."""
    trade = {
        "timestamp": format_log_time(),
        "signal":    signal,
        "symbol":    symbol,
        "qty":       qty,
        "price":     price,
        "result":    result,
    }
    with _lock:
        _trades.append(trade)
    logger.info(f"📝 Trade registrado: {trade}")

def get_trades() -> list:
    with _lock:
        return _trades.copy()

def clear_trades():
    with _lock:
        _trades.clear()
    logger.info("🗑️ Historial de trades limpiado")
