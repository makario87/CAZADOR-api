"""
logs/logger.py
Sistema de logs centralizado.
Salida: consola (stdout) + archivo /tmp/cazador.log con rotación diaria.
"""
import logging
import sys
from logging.handlers import TimedRotatingFileHandler

LOG_FORMAT   = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
LOG_LEVEL    = logging.INFO
LOG_FILE     = "/tmp/cazador.log"


def get_logger(name: str) -> logging.Logger:
    """Retorna logger configurado para el módulo dado."""
    logger = logging.getLogger(name)

    if not logger.handlers:
        formatter = logging.Formatter(LOG_FORMAT)

        # Handler 1 — consola (igual que antes)
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

        # Handler 2 — archivo /tmp/cazador.log
        # Rota cada día a medianoche UTC, guarda 7 días
        try:
            file_handler = TimedRotatingFileHandler(
                LOG_FILE,
                when="midnight",
                interval=1,
                backupCount=7,
                utc=True,
            )
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)
        except Exception as e:
            # Si /tmp no es accesible no rompemos el arranque
            logger.warning(f"⚠️ No se pudo crear log en archivo: {e}")

        logger.setLevel(LOG_LEVEL)

    return logger
