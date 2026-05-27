"""
utils/security.py
Validaciones webhook:
- Schema validation
- Anti-duplicados
"""

import time
import hashlib
from threading import Lock

from config.settings import WEBHOOK_REQUIRED_FIELDS, DEDUP_WINDOW_SEC

# Store temporal en memoria
_dedup_store: dict[str, float] = {}
_dedup_lock = Lock()


# ============================================================
# Schema validation
# ============================================================

def validate_schema(payload: dict) -> tuple[bool, str]:
    """
    Comprueba que el payload contiene todos los campos obligatorios.
    """
    missing = [f for f in WEBHOOK_REQUIRED_FIELDS if not payload.get(f)]

    if missing:
        return False, f"Campos obligatorios ausentes: {missing}"

    return True, "ok"


# ============================================================
# Anti-duplicados
# ============================================================

def _signal_hash(payload: dict) -> str:
    """
    Hash único por señal.
    """
    key = (
        f"{payload.get('robot')}|"
        f"{payload.get('symbol')}|"
        f"{payload.get('signal')}|"
        f"{payload.get('time')}"
    )

    return hashlib.sha256(key.encode()).hexdigest()


def validate_no_duplicate(payload: dict) -> tuple[bool, str]:
    """
    Rechaza señales duplicadas dentro de ventana temporal.
    """
    now = time.time()

    sig_hash = _signal_hash(payload)

    with _dedup_lock:

        # limpiar expirados
        expired = [
            h for h, t in _dedup_store.items()
            if now - t > DEDUP_WINDOW_SEC
        ]

        for h in expired:
            del _dedup_store[h]

        # duplicado
        if sig_hash in _dedup_store:
            return False, "duplicate"

        # registrar
        _dedup_store[sig_hash] = now

    return True, "ok"
