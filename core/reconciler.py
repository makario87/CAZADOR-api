"""
core/reconciler.py

Reconciliador real: compara estado Python vs estado BingX.
Detecta desync y activa emergencia si es necesario.

FASE ACTUAL:
- compara si hay posición o no
- compara dirección LONG/SHORT

FASE FUTURA:
- qty exacta
- precio entrada
- pnl
"""
import threading
import time

from brokers.bingx import get_positions, get_balance
from core.emergency import trigger_emergency
from data.state import (
    get_state,
    update_position,
    record_reconciler,
)
from config.settings import RECONCILE_INTERVAL, DEMO_MODE
from logs.logger import get_logger

logger = get_logger(__name__)

_reconciler_thread = None


# ============================================================
# 🚀 ARRANQUE
# ============================================================
def start_reconciler():

    global _reconciler_thread

    if _reconciler_thread and _reconciler_thread.is_alive():
        return

    _reconciler_thread = threading.Thread(
        target=_reconcile_loop,
        daemon=True
    )

    _reconciler_thread.start()

    logger.info(
        f"🔄 Reconciliador arrancado "
        f"(cada {RECONCILE_INTERVAL}s)"
    )


def is_alive() -> bool:
    return (
        _reconciler_thread is not None
        and
        _reconciler_thread.is_alive()
    )


# ============================================================
# 🔄 LOOP
# ============================================================
def _reconcile_loop():

    while True:

        try:
            time.sleep(RECONCILE_INTERVAL)
            _check_state()

        except Exception as e:
            logger.error(f"❌ Error en reconciliador: {e}")


# ============================================================
# 🔍 CHECK REAL
# ============================================================
def _check_state():
    """
    Compara Python vs BingX REAL.
    """

    record_reconciler()

    # ========================================================
    # 📡 CONSULTAR BINGX
    # ========================================================
    bingx_data = get_positions()

    if not bingx_data:
        logger.warning("⚠️ Reconciliador sin respuesta BingX")
        return

    if bingx_data.get("code") != 0:
        logger.warning(
            f"⚠️ Reconciliador no pudo consultar BingX: "
            f"{bingx_data}"
        )
        return

    # ========================================================
    # 📋 PARSEAR POSICIONES REALES
    # ========================================================
    positions = bingx_data.get("data", {}).get("positions", [])

    bingx_long = any(
        p.get("positionSide") == "LONG"
        and
        float(p.get("positionAmt", 0)) != 0
        for p in positions
    )

    bingx_short = any(
        p.get("positionSide") == "SHORT"
        and
        float(p.get("positionAmt", 0)) != 0
        for p in positions
    )

    # ========================================================
    # 🧠 ESTADO PYTHON
    # ========================================================
    state = get_state()

    python_long  = state.get("position_long", False)
    python_short = state.get("position_short", False)
    symbol       = state.get("position_symbol", "?")

    logger.info(
        f"🔍 Reconciliación: "
        f"Python(L={python_long} S={python_short}) "
        f"vs "
        f"BingX(L={bingx_long} S={bingx_short})"
    )

    # ========================================================
    # ✅ TODO SINCRONIZADO
    # ========================================================
    if (
        python_long  == bingx_long
        and
        python_short == bingx_short
    ):
        logger.info("✅ Estado sincronizado correctamente")
        return

    # ========================================================
    # ⚠️ BingX tiene LONG que Python no sabe
    # ========================================================
    if bingx_long and not python_long:

        logger.warning(
            "⚠️ DESYNC: BingX tiene LONG "
            "pero Python no lo sabe"
        )

        update_position(
            symbol,
            has_long=True,
            has_short=False
        )

        if not DEMO_MODE:
            trigger_emergency(
                "DESYNC: BingX tiene LONG no registrado"
            )

        return

    # ========================================================
    # ⚠️ BingX tiene SHORT que Python no sabe
    # ========================================================
    if bingx_short and not python_short:

        logger.warning(
            "⚠️ DESYNC: BingX tiene SHORT "
            "pero Python no lo sabe"
        )

        update_position(
            symbol,
            has_long=False,
            has_short=True
        )

        if not DEMO_MODE:
            trigger_emergency(
                "DESYNC: BingX tiene SHORT no registrado"
            )

        return

    # ========================================================
    # 🚨 Python cree LONG pero BingX no
    # ========================================================
    if python_long and not bingx_long:

        logger.error(
            "🚨 DESYNC CRÍTICO: "
            "Python cree LONG "
            "pero BingX no tiene nada"
        )

        update_position(
            symbol,
            has_long=False,
            has_short=False
        )

        if not DEMO_MODE:
            trigger_emergency(
                "DESYNC CRÍTICO LONG"
            )

        return

    # ========================================================
    # 🚨 Python cree SHORT pero BingX no
    # ========================================================
    if python_short and not bingx_short:

        logger.error(
            "🚨 DESYNC CRÍTICO: "
            "Python cree SHORT "
            "pero BingX no tiene nada"
        )

        update_position(
            symbol,
            has_long=False,
            has_short=False
        )

        if not DEMO_MODE:
            trigger_emergency(
                "DESYNC CRÍTICO SHORT"
            )

        return


# ============================================================
# 🧪 RECONCILIACIÓN MANUAL
# ============================================================
def reconcile_now(symbol: str = "") -> dict:

    record_reconciler()

    balance   = get_balance()
    positions = get_positions(symbol)

    return {
        "balance": balance,
        "positions": positions
    }
