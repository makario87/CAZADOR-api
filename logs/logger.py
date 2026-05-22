"""
logs/logger.py
Sistema de logs centralizado.
"""
import logging
import sys

LOG_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
LOG_LEVEL  = logging.INFO

def get_logger(name: str) -> logging.Logger:
    """Retorna logger configurado para el módulo dado."""
    logger = logging.getLogger(name)

    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter(LOG_FORMAT))
        logger.addHandler(handler)
        logger.setLevel(LOG_LEVEL)

    return logger
