# Pirámide y GIROS
**Versión: v7 | Sesión 5**

---

## Filosofía

- **TV es la fuente de verdad** — TV sabe cuántas entradas hay abiertas
- **Python solo ejecuta** — no calcula pirámide, solo la registra
- **Pirámide acumulativa** — BingX fusiona LONG+LONG en una línea (same-side fusion)
- **Cierre de golpe** — cuando TV manda SL/CLOSE, Python cierra toda la posición acumulada

---

## Control de pirámide

TV manda en cada ENTRY/GIRO:
- `pyramid_current`: cuántas entradas hay abiertas AHORA según TV
- `pyramid_max`: máximo configurado en la estrategia

Python rechaza si `pyramid_current > pyramid_max`:
```python
if pyramid_current > pyramid_max:
    return {"status": "rejected", "reason": "pyramid_full"}
```

Rechazo limpio: sin emergencia, robot sigue activo.

---

## Contadores en state

Por símbolo y lado:
```python
positions[symbol]["pyramid_long_count"]   # entradas LONG acumuladas
positions[symbol]["pyramid_short_count"]  # entradas SHORT acumuladas
```

Se incrementan en `increment_pyramid()` tras cada ENTRY/GIRO exitoso.
Se resetean a 0 en `update_position()` al cerrar.

---

## Bug pirámide aditiva (#9b) — RESUELTO

**Causa raíz:** `_giro_long()` y `_giro_short()` abrían posición pero NO llamaban a `increment_pyramid()` ni `update_bar_time()`.

**Resultado:** contador arrancaba en 0 tras GIRO → primera ENTRY posterior mostraba 1 en vez de 2.

**Fix:** añadir tras `update_entry()` en ambos GIROS:
```python
increment_pyramid(symbol, "LONG")  # o "SHORT"
update_bar_time(symbol, payload.get("time", ""), payload.get("tf", ""))
```

**Validación:**
- GIRO → pirámide=1 ✅
- ENTRY posterior → pirámide=2 ✅
- ENTRY posterior → pirámide=3 ✅

---

## Precio medio ponderado

En cada entrada de pirámide, `update_entry()` recalcula el precio medio real:

```python
avg_price = ((prev_price * prev_qty) + (price * qty)) / new_qty
```

Permite calcular PnL real con múltiples entradas acumuladas.

---

## BingX same-side fusion

BingX en Hedge Mode fusiona todas las entradas LONG en una sola línea:
```
ENTRY 1: 0.0013 BTC LONG
ENTRY 2: 0.0013 BTC LONG
ENTRY 3: 0.0013 BTC LONG
→ BingX muestra: 1 posición LONG de 0.0039 BTC
```

"Posiciones abiertas: 1" NO significa "1 entrada".
La validación real es qty acumulada + reconciler + state + cierre correcto.

---

## GIROS

Flujo GIRO_LONG (viene de posición SHORT):
```
1. close_all_positions(symbol, "SHORT")
2. sleep(GIRO_BUFFER_SECONDS)   ← 0.3s para que BingX procese el cierre
3. calcular qty nueva
4. place_order("BUY", "LONG")
5. si OK: update_state + update_position + update_entry
          + increment_pyramid(1) + update_bar_time
          + _send_sl_broker()    ← nuevo STOP_MARKET lado LONG
```

Si el cierre falla → trigger_emergency + abort (no abrir nuevo lado).
Si el cierre OK pero apertura falla → trigger_emergency (quedamos flat).

### GIRO sin posición previa
Si BingX ya estaba plano (posición cerrada externamente):
- El cierre devuelve `no_open_position`
- GIRO continúa y abre directamente el nuevo lado
- Sin emergencia, sin bloqueo

---

## Anti-duplicados por vela

Garantiza máximo 1 entrada por vela por símbolo:

```python
if signal_time == last_bar_time and signal_tf == last_bar_tf:
    return {"status": "rejected", "reason": "duplicate_entry_same_bar"}
```

`update_bar_time()` guarda `(bar_time, bar_tf)` tras cada ENTRY/GIRO exitoso.
TV usa `timenow` → señales nunca expiran artificialmente.

---

## Bloqueo pirámide por profit (Pine)

Pine tiene lógica de bloqueo cuando el profit supera umbral:
```pine
lockPyramidLong = usePyrProfitLock and strategy.position_size > 0 
                  and profitLong >= pyrProfitPct
```

Si `lockPyramidLong = true` → TV no manda ENTRY → Python nunca ve la señal.

---

## Distancia mínima entre entradas (Pine)

```pine
distLongOK = strategy.position_size <= 0 or
             close > lastEntryPriceLong * (1 + minDistPct / 100)
```

Evita entradas demasiado juntas. Configurable desde Pine.
