"""
utils/time_utils.py
Helpers de tiempo y timestamps.
"""
import time
from datetime import datetime, timezone
from config.settings import SIGNAL_EXPIRY_SECONDS

def now_utc() -> datetime:
    """Retorna datetime actual en UTC."""
    return datetime.now(timezone.utc)

def now_ms() -> int:
    """Timestamp actual en milisegundos (para firma BingX)."""
    return int(time.time() * 1000)

def is_signal_expired(signal_timestamp: str) -> bool:
    """
    Verifica si una señal de TradingView es demasiado antigua.
    TradingView manda el timestamp en formato ISO 8601.
    """
    try:
        signal_time = datetime.fromisoformat(signal_timestamp.replace("Z", "+00:00"))
        age_seconds = (now_utc() - signal_time).total_seconds()
        return age_seconds > SIGNAL_EXPIRY_SECONDS
    except Exception:
        # Si no podemos parsear el timestamp, no expiramos por seguridad
        return False

def format_log_time() -> str:
    """Formato legible para logs."""
    return now_utc().strftime("%Y-%m-%d %H:%M:%S UTC")
