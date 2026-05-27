# Sistema de Señales
**Versión: v7 | Sesión 5**

---

## Señales válidas

```python
VALID_SIGNALS = {
    "ENTRY_LONG", "ENTRY_SHORT",
    "CLOSE_LONG", "CLOSE_SHORT",
    "GIRO_LONG",  "GIRO_SHORT",
    "SL_LONG_DYNAMIC",  "SL_SHORT_DYNAMIC",
    "SL_LONG_BLACK",    "SL_SHORT_BLACK",
    "SL_LONG_CCI",      "SL_SHORT_CCI",
    "SL_LONG_PROMEDIO", "SL_SHORT_PROMEDIO",
    "SL_LONG_LAST",     "SL_SHORT_LAST",
}
```

---

## JSON base (todas las señales)

```json
{
  "signal":  "ENTRY_LONG",
  "robot":   "CAZADOR",
  "symbol":  "BTCUSDT.P",
  "tf":      "15",
  "price":   "95000.0",
  "time":    "2026-05-26T12:00:00Z",
  "token":   "TOKEN_AQUI"
}
```

## JSON ENTRY / GIRO (añaden pirámide + sl_broker)

```json
{
  "signal":          "ENTRY_LONG",
  "robot":           "CAZADOR",
  "symbol":          "BTCUSDT.P",
  "tf":              "15",
  "price":           "95000.0",
  "time":            "2026-05-26T12:00:00Z",
  "token":           "TOKEN_AQUI",
  "pyramid_max":     "3",
  "pyramid_current": "1",
  "sl_broker":       "93100.0"
}
```

`sl_broker = "0"` si `useSL = false` en Pine → Python omite STOP_MARKET.

---

## Flujo de validación antes de ejecutar

```
1. ¿Señal en VALID_SIGNALS?          → si no: ignorar
2. ¿Es ENTRY?                         → control pirámide
   pyramid_current > pyramid_max      → rechazar (pyramid_full)
   misma vela que última entrada      → rechazar (duplicate_entry_same_bar)
3. ¿Emergencia activa?
   señal en PROTECTION_SIGNALS        → ejecutar igualmente
   señal normal                       → bloquear (emergency_active)
4. Dispatch a función específica
```

---

## PROTECTION_SIGNALS — nunca bloqueadas por emergencia

```python
PROTECTION_SIGNALS = {
    "CLOSE_LONG", "CLOSE_SHORT",
    "GIRO_LONG",  "GIRO_SHORT",
    "SL_LONG_DYNAMIC",  "SL_SHORT_DYNAMIC",
    "SL_LONG_BLACK",    "SL_SHORT_BLACK",
    "SL_LONG_CCI",      "SL_SHORT_CCI",
    "SL_LONG_PROMEDIO", "SL_SHORT_PROMEDIO",
    "SL_LONG_LAST",     "SL_SHORT_LAST",
}
```

---

## Flujo por tipo de señal

### ENTRY_LONG / ENTRY_SHORT
```
calcular qty (balance × RISK_PCT / precio)
place_order() → BUY/SELL MARKET
si code==0:
  update_state()
  update_position()
  update_entry()        ← precio medio ponderado
  increment_pyramid()
  update_bar_time()     ← anti-duplicados
  _send_sl_broker()     ← STOP_MARKET airbag (#11)
```

### CLOSE_LONG / CLOSE_SHORT
```
close_all_positions() → lee qty real de BingX
si code==0:
  update_state()
  update_position(has_long=False, has_short=False)
si no_open_position:
  actualizar state igualmente (ya estaba cerrado)
si error real:
  trigger_emergency()
```

### GIRO_LONG / GIRO_SHORT
```
close_all_positions() lado contrario
sleep(GIRO_BUFFER_SECONDS)  ← 0.3s por defecto
calcular qty
place_order() nuevo lado
si code_open==0:
  update_state()
  update_position()
  update_entry()
  increment_pyramid()    ← pirámide arranca en 1 tras GIRO
  update_bar_time()
  _send_sl_broker()      ← nuevo STOP_MARKET lado nuevo (#11)
si cierre falla:
  trigger_emergency() + abort (no abrir nuevo lado)
si apertura falla:
  trigger_emergency() (lado anterior ya cerrado)
```

### SL_LONG_* / SL_SHORT_*
```
close_all_positions() lado correspondiente
si code==0:
  update_state()
  update_position(has_long=False, has_short=False)
si no_open_position:
  actualizar state (ya cerrado externamente)
si error:
  trigger_emergency()
```

---

## Anti-duplicados por vela

Para ENTRY_LONG y ENTRY_SHORT:

```python
signal_time = payload.get("time", "")
signal_tf   = payload.get("tf", "")
last_bar_time, last_bar_tf = get_bar_time(symbol)

if signal_time == last_bar_time and signal_tf == last_bar_tf:
    → rechazar: duplicate_entry_same_bar
```

Garantiza máximo 1 entrada por vela por símbolo.
TV usa `timenow` → señales nunca expiran por tiempo.

---

## Pine Script — bloque alertas

Regla JSON:
- Abre posición (ENTRY, GIRO) → usa `_base_entry` (lleva pyramid_max + pyramid_current + sl_broker)
- Cierra posición (SL, CLOSE) → usa `_base` (sin pirámide ni sl_broker)

```pine
string _base = '"robot":"' + ROBOT_NAME + '","symbol":"' + _sym + 
               '","tf":"' + _tf + '","price":"' + _px + 
               '","time":"' + _time + '","token":"' + WEBHOOK_TOKEN + '"'

string _base_entry = _base + 
    ',"pyramid_max":"'     + _pyr_max + 
    '","pyramid_current":"' + _pyr_current + 
    '","sl_broker":"'      + _sl_broker + '"'
```

---
## Sesión 6 — Schema validation + Anti-duplicados

### Capa 3 — Schema validation
Campos obligatorios: `signal`, `robot`, `symbol`, `tf`, `price`, `time`, `token`
Fallo → 400 Bad Request + Emergency Mode para ese robot.
Implementado en `utils/security.py` → `validate_schema()`

### Capa 5 — Anti-duplicados
Hash: `robot + symbol + signal + time[:16]`
- `time[:16]` truncado a minuto — misma vela = duplicado
- Ventana: 5 segundos (`DEDUP_WINDOW_SEC=5`)
- NO activa Emergency — puede ser retry legítimo
- 409 Duplicate signal
Implementado en `utils/security.py` → `validate_no_duplicate()`

### Tabla respuestas actualizada
| Código | Causa | Emergency |
|---|---|---|
| 200 queued | Señal válida | No |
| 200 expired | Timestamp expirado | No |
| 400 Bad Request | Schema inválido | ✅ Sí |
| 401 Unauthorized | Token inválido | ✅ Sí |
| 409 Duplicate | Anti-duplicados | No |
