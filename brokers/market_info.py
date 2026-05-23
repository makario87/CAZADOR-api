"""
brokers/market_info.py

Consulta y cachea información de contratos BingX.
Proporciona quantity_precision, min_qty y step_size por símbolo.

Endpoint público — no requiere firma.
Caché en memoria con TTL de 1 hora.
"""
import time
import requests
from config.settings import BINGX_BASE_URL
from logs.logger import get_logger

logger = get_logger(__name__)

# ============================================================
# 📦 CACHÉ EN MEMORIA
# ============================================================
_cache: dict = {}          # {"PENGU-USDT": {quantity_precision, min_qty, ...}}
_cache_ts: float = 0.0
_CACHE_TTL = 3600          # 1 hora — los contratos no cambian frecuentemente

# ============================================================
# 📡 CONSULTA AL BROKER
# ============================================================

def _fetch_contracts() -> dict:
    """
    GET /openApi/swap/v2/quote/contracts — endpoint público, sin firma.
    Devuelve dict indexado por símbolo: {"PENGU-USDT": {...}, ...}
    """
    url = f"{BINGX_BASE_URL}/openApi/swap/v2/quote/contracts"
    try:
        resp = requests.get(url, timeout=10)
        data = resp.json()
        if data.get("code") != 0:
            logger.error(f"❌ market_info: error API: {data.get('msg')}")
            return {}

        contracts = data.get("data", [])
        result = {}
        for c in contracts:
            sym = c.get("symbol", "")
            if not sym:
                continue
            result[sym] = {
                "quantity_precision": int(c.get("quantityPrecision", 0)),
                "price_precision":    int(c.get("pricePrecision", 4)),
                "min_qty":            float(c.get("tradeMinQuantity", 1)),
                "min_usdt":           float(c.get("tradeMinUSDT", 1)),
                "max_leverage":       int(c.get("maxLeverage", 100)),
            }

        logger.info(f"✅ market_info: {len(result)} contratos cargados")
        return result

    except Exception as e:
        logger.error(f"❌ market_info: error consultando contratos: {e}")
        return {}

def _get_cache() -> dict:
    """Devuelve caché vigente, recargando si expiró."""
    global _cache, _cache_ts
    if not _cache or (time.time() - _cache_ts) > _CACHE_TTL:
        fresh = _fetch_contracts()
        if fresh:
            _cache = fresh
            _cache_ts = time.time()
    return _cache

# ============================================================
# 🔢 FUNCIÓN PÚBLICA — redondear qty según contrato
# ============================================================

def round_qty(symbol: str, qty: float) -> float:
    """
    Redondea qty según quantity_precision y min_qty del contrato.

    quantity_precision=0  → entero       (ej. PENGU: 11166)
    quantity_precision=1  → 1 decimal    (ej. 11166.5)
    quantity_precision=3  → 3 decimales  (ej. BTC: 0.001)

    Si el símbolo no está en caché, devuelve round(qty, 0) como fallback seguro.
    """
    cache = _get_cache()
    info  = cache.get(symbol)

    if not info:
        # Símbolo no encontrado — fallback: entero
        logger.warning(f"⚠️ market_info: {symbol} no encontrado en contratos — usando entero")
        rounded = float(int(qty))
        return max(1.0, rounded)

    precision = info["quantity_precision"]
    min_qty   = info["min_qty"]

    rounded = round(qty, precision)
    if precision == 0:
        rounded = int(rounded)

    # Respetar mínimo del contrato
    if rounded < min_qty:
        logger.warning(
            f"⚠️ [{symbol}] qty={rounded} < min_qty={min_qty} — "
            f"ajustando al mínimo"
        )
        rounded = min_qty

    return rounded

def format_qty(symbol: str, qty: float) -> str:
    """
    Formatea qty como string según quantityPrecision del contrato.
    precision=0 → "10970"   (entero puro)
    precision=1 → "10970.0" (1 decimal)
    precision=3 → "0.001"   (3 decimales)

    Usar esto en vez de str(qty) al construir params de orden.
    """
    cache = _get_cache()
    info  = cache.get(symbol)

    precision = info["quantity_precision"] if info else 0

    if precision == 0:
        return str(int(round(qty, 0)))
    else:
        return str(round(qty, precision))
        
def get_symbol_info(symbol: str) -> dict:
    """Devuelve info completa del contrato. Útil para logs y debugging."""
    return _get_cache().get(symbol, {})

def preload():
    """Precarga caché al arrancar el sistema."""
    _get_cache()
    logger.info("📦 market_info precargado")
