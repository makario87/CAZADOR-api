# Sistema de Stop Loss
**Versión: v7 | Sesión 5**

---

## Arquitectura general

```
TV (cerebro) → calcula y gestiona TODOS los SL estratégicos
Python       → ejecuta cierre cuando TV manda señal SL_*
BingX        → STOP_MARKET solo como airbag de emergencia
```

**TV siempre cierra antes que BingX.** BingX solo actúa si TV y Python fallan.

---

## Tipos de SL en CAZADOR (gestionados por TV)

| Señal | Tipo | Descripción |
|---|---|---|
| `SL_LONG_DYNAMIC` | Dinámico | Basado en triángulos/señales Pine |
| `SL_SHORT_DYNAMIC` | Dinámico | Mismo, lado SHORT |
| `SL_LONG_BLACK` | Dinámico | Basado en negras contrarias acumuladas |
| `SL_SHORT_BLACK` | Dinámico | Mismo, lado SHORT |
| `SL_LONG_CCI` | Dinámico | Basado en toques CCI consecutivos |
| `SL_SHORT_CCI` | Dinámico | Mismo, lado SHORT |
| `SL_LONG_PROMEDIO` | Fijo | % sobre precio promedio de posición |
| `SL_SHORT_PROMEDIO` | Fijo | Mismo, lado SHORT |
| `SL_LONG_LAST` | Fijo | % sobre precio de última entrada |
| `SL_SHORT_LAST` | Fijo | Mismo, lado SHORT |

---

## Flujo SL gestionado por TV

```
Pine detecta toque de SL
→ construye JSON con signal=SL_LONG_*/SL_SHORT_*
→ webhook → Python
→ signal_handler._sl_long() / _sl_short()
→ close_all_positions() — cierra TODO el lado acumulado
→ update_state() + update_position()
```

Todos los SL comparten el mismo flujo de ejecución en Python.
La diferencia es solo semántica (qué tipo de SL disparó TV).

---

## SL broker — airbag BingX (#11)

### Filosofía
- TV calcula el precio real y lo manda en `sl_broker`
- Python NO decide estrategia ni precio
- Python solo añade margen de emergencia del 1%
- Si TV cierra primero → STOP BingX queda huérfano inofensivo
- Si TV/Python fallan → BingX salva en precio de emergencia

### Cuándo se crea
Solo en ENTRY y GIRO (apertura de posición), nunca en cierres.
Solo si `useSL = true` en Pine (Promediado o Última entrada).
Si `useSL = false` → `sl_broker = "0"` → Python omite STOP_MARKET.

### Cálculo del margen emergencia
```python
# LONG: BingX por debajo del SL de TV
sl_final = sl_broker_tv × 0.99

# SHORT: BingX por encima del SL de TV
sl_final = sl_broker_tv × 1.01
```

Ejemplo LONG:
```
TV SL = 100.00
BingX  = 99.00  ← precio baja → TV cierra en 100 → BingX en 99 nunca dispara
```

### Flujo completo (#11)
```
_send_sl_broker(symbol, position_side, qty, sl_broker_str, robot)

1. sl_broker_raw = float(sl_broker_str)
   si <= 0 → omitir (useSL OFF)

2. calcular sl_final con margen 1%

3. get_sl_broker_order_id(symbol, position_side)
   si existe order_id previo:
     cancel_order(symbol, order_id)  ← DELETE BingX
     set_sl_broker_order_id(symbol, position_side, None)

4. place_stop_order(symbol, close_side, position_side, sl_final, qty)

5. si code==0:
     order_id = result["_meta"]["order_id"]
     set_sl_broker_order_id(symbol, position_side, order_id)
   si code!=0:
     logger.warning()  ← solo warning, sin emergencia
```

### Refresco en pirámide
Cada nueva ENTRY/pirámide/GIRO:
- Cancela el STOP anterior
- Crea STOP nuevo con precio actualizado
- Nunca se acumulan STOPs simultáneos

### Limpieza al cerrar
`update_position()` con `has_long=False` o `has_short=False`:
```python
pos["sl_broker_order_id_long"]  = None
pos["sl_broker_order_id_short"] = None
```

---

## SL dinámicos (DYNAMIC, BLACK, CCI) — no usan sl_broker

Los SL dinámicos los gestiona TV completamente:
- TV actualiza el precio vela a vela
- Cuando toca → TV manda señal SL_LONG_DYNAMIC etc.
- Python cierra → BingX ejecuta

El STOP_MARKET de BingX es fijo (precio de cuando se abrió).
TV siempre cerrará antes porque su SL dinámico va por delante.

---

## Identificador del SL activo en Pine

Pine determina qué SL está activo en cada momento:
```pine
if not na(blackSlLong) and slLong == blackSlLong
    slReasonLong := "SL_LONG_BLACK"
else if not na(cciSlLong) and slLong == cciSlLong
    slReasonLong := "SL_LONG_CCI"
else if not na(dynSlLong) and slLong == dynSlLong
    slReasonLong := "SL_LONG_DYNAMIC"
else if not na(baseSlLong)
    slReasonLong := slMode == "Promediado"
         ? "SL_LONG_PROMEDIO" : "SL_LONG_LAST"
```

La señal que llega a Python ya identifica exactamente qué SL disparó.

---

## Casos validados (#11)

| Caso | Resultado |
|---|---|
| useSL OFF | sl_broker=0 → sin STOP BingX ✅ |
| useSL ON Promediado | STOP creado correctamente ✅ |
| useSL ON Última entrada | STOP creado correctamente ✅ |
| Pirámide nueva entrada | STOP anterior cancelado → nuevo creado ✅ |
| GIRO | STOP nuevo lado creado correctamente ✅ |
| BingX rechaza STOP | Solo warning → robot sigue ✅ |
| Multi-symbol BTC+PENGU | Sin contaminación cruzada ✅ |
| STOPs acumulados | Ya no ocurre — cancelar→crear ✅ |
