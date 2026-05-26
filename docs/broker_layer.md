# Broker Layer — BingX API
**Versión: v7 | Sesión 5**

---

## Conexión

- Endpoint demo: `https://open-api-vst.bingx.com`
- Endpoint live: `https://open-api.bingx.com`
- Autenticación: HMAC SHA256 — header `X-BX-APIKEY`
- Modo: Hedge Mode obligatorio (LONG y SHORT independientes)

---

## Reglas críticas BingX

```
POST sin Content-Type          → CRÍTICO (con Content-Type da error 109400)
data={} en POST                → dict vacío, NO b""
headers = {"X-BX-APIKEY": KEY} → solo esto
positionAmt SHORT es negativo  → usar abs() siempre
clientOrderID obligatorio      → uuid4 en cada orden
code=0                         → éxito
code=101500                    → "system busy" → reintentar
code=109400                    → timestamp inválido o Content-Type incorrecto
```

---

## Normalización de símbolos

TradingView envía símbolos en formato exchange, BingX espera formato con guión:

```
PENGUUSDT.P  → PENGU-USDT
BTCUSDT.P    → BTC-USDT
1000PEPEUSDT.P → 1000PEPE-USDT
```

Regla automática: quitar `.P`/`.PERP`, insertar `-` antes de USDT/BUSD/USDC/BTC/ETH.
Tabla de excepciones `_SYMBOL_EXCEPTIONS` para pares que no siguen el patrón.

---

## Retry automático

```python
_RETRYABLE_CODES = {101500}  # "system busy"
_RETRY_ATTEMPTS  = 3
_RETRY_DELAY     = 0.5       # segundos
```

Flujo:
- `code == 0` → éxito inmediato
- `code in _RETRYABLE_CODES` → espera y reintenta
- Otro código → error permanente, salida inmediata
- Excepción de red → cuenta como intento, reintenta
- Agotados intentos → return último data conocido

---

## Funciones principales

### `place_order()`
Orden de mercado. Parámetros: `symbol, side, quantity, position_side, price_signal, robot`

```python
params = {
    "clientOrderID": uuid4,
    "positionSide":  "LONG" | "SHORT",
    "quantity":      qty_str,
    "side":          "BUY" | "SELL",
    "symbol":        "BTC-USDT",
    "type":          "MARKET",
}
```

Retorna `_meta` con: `robot, symbol, side, position_side, qty_executed, price_signal, price_executed, slippage, commission, order_id, client_order_id`

### `place_stop_order()` (#11)
STOP_MARKET como red de seguridad (SL broker airbag).

```python
params = {
    "clientOrderID": uuid4,
    "positionSide":  "LONG" | "SHORT",
    "quantity":      qty_str,
    "side":          "BUY" | "SELL",
    "symbol":        "BTC-USDT",
    "type":          "STOP_MARKET",
    "stopPrice":     str(stop_price),
}
```

Retorna `_meta` con: `order_id, client_order_id`

### `cancel_order()` (#11)
Cancela orden pendiente por orderId. Usado para cancelar STOP anterior antes de crear uno nuevo.

```
DELETE /openApi/swap/v2/trade/order
params: symbol + orderId
```

Si la orden ya ejecutó o no existe → solo warning, sin emergencia.

### `close_position()`
Cierra posición total. Si `quantity=None` consulta qty real en BingX antes de cerrar.
Usa `abs()` en positionAmt — SHORT tiene valor negativo en BingX.

### `close_all_positions()`
Alias de `close_position()` con `position_side` como parámetro.

### `get_balance()`
Consulta balance disponible. Usado por sizing en signal_handler.

### `get_positions(symbol)`
Consulta posiciones abiertas. Filtra `positionAmt != 0`.

### `get_order_history(symbol, limit)`
Historial últimas N órdenes. Usado por reconciler para detectar cierres externos.

### `ping_bingx()`
Comprueba conectividad. Retorna True/False. Usado por watchdog.

---

## Sizing dinámico

```python
margen  = balance_disponible × RISK_PCT
qty     = margen / precio_actual
qty_str = round_qty(symbol, qty)  # stepSize real del contrato
```

Validación: si `qty_rounded < min_qty` → orden rechazada, log warning.
BingX aplica el leverage configurado manualmente en el broker.

---

## Precisión por contrato

```
quantity_precision=0 → entero (PENGU)
quantity_precision=3 → 0.001 (BTC)
```

`market_info.py` cachea contratos 1 hora para no repetir consultas.

---

## BingX same-side fusion (Hedge Mode)

BingX fusiona LONG+LONG en una sola línea acumulada:
- "Posiciones abiertas: 1" NO significa "1 entrada"
- Significa "1 side activo"
- La validación real es qty acumulada + reconciler + state + cierre correcto
- Ejemplo: 3×0.0013 BTC = 0.0039 qty acumulada, cierre correcto de golpe
