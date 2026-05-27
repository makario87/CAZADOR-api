# Sistema de Estado
**Versión: v7 | Sesión 5**

---

## Filosofía

- **State no miente** — nunca se actualiza si BingX falla
- **Persistencia mínima** — JSON en /tmp (sobrevive reinicios, no deploys)
- **Multi-symbol desde el inicio** — `positions[symbol]` como estructura principal
- **Campos legacy** — mantenidos temporalmente para compatibilidad

---

## Estructura completa

```python
_state = {
    # — sistema —
    "emergency":                    False,
    "emergency_reason":             None,
    "last_signal":                  None,
    "symbol":                       None,
    "blocked":                      False,
    "last_webhook_time":            None,
    "last_reconciler_time":         None,
    "last_webhook_signal":          None,
    "webhooks_received":            0,
    "webhooks_ok":                  0,
    "webhooks_failed":              0,
    "started_at":                   None,

    # — detección actividad externa —
    "our_client_order_ids":         [],
    "external_close_detected":      False,
    "external_activity_detected":   False,

    # — MULTI-SÍMBOLO — estructura principal —
    "positions": {
        "BTC-USDT": {
            "long":                      False,
            "short":                     False,
            "entry_price_long":          None,
            "entry_price_short":         None,
            "entry_qty_long":            None,
            "entry_qty_short":           None,
            "pyramid_long_count":        0,
            "pyramid_short_count":       0,
            "last_entry_bar_time":       None,
            "last_entry_bar_tf":         None,
            "sl_broker_order_id_long":   None,  # ← #11
            "sl_broker_order_id_short":  None,  # ← #11
        }
    },

    # — LEGACY — campos planos compatibilidad temporal —
    "position_long":                False,
    "position_short":               False,
    "position_symbol":              None,
    "entry_price_long":             None,
    "entry_price_short":            None,
    "entry_qty_long":               None,
    "entry_qty_short":              None,
    "pyramid_long_count":           0,
    "pyramid_short_count":          0,
    "last_entry_bar_time":          None,
    "last_entry_bar_tf":            None,
}
```

---

## Funciones principales

| Función | Descripción |
|---|---|
| `get_state()` | Devuelve copia del estado global |
| `get_position(symbol)` | Posición de un símbolo concreto |
| `get_all_positions()` | Todos los símbolos con posición abierta |
| `update_state(updates)` | Actualiza campos globales |
| `update_position(symbol, has_long, has_short)` | Actualiza posición + limpia campos al cerrar |
| `update_entry(symbol, side, price, qty)` | Precio medio ponderado en pirámide |
| `increment_pyramid(symbol, side)` | Incrementa contador pirámide |
| `update_bar_time(symbol, bar_time, tf)` | Anti-duplicados por vela |
| `get_bar_time(symbol)` | Lee tiempo última entrada |
| `register_our_order(client_order_id)` | Registra orderId propio (detección externa) |
| `set_sl_broker_order_id(symbol, side, order_id)` | Guarda orderId STOP_MARKET activo |
| `get_sl_broker_order_id(symbol, side)` | Lee orderId STOP_MARKET activo |
| `set_flag(key, value)` | Escribe flag booleano (external_close_detected etc.) |
| `reset_state()` | Reset completo — limpia todo |
| `save_state()` | Persiste en /tmp/cazador_state.json |
| `load_state()` | Carga desde disco al arrancar |

---

## Precio medio ponderado (pirámide)

En cada nueva entrada de pirámide, `update_entry()` recalcula el precio medio:

```python
avg_price = ((prev_price * prev_qty) + (price * qty)) / new_qty
```

Esto permite calcular PnL real con múltiples entradas.

---

## Detección actividad externa

Tres flags para detectar actividad fuera del flujo esperado:

| Flag | Cuándo se activa |
|---|---|
| `external_close_detected` | Reconciler detecta posición cerrada sin señal Python |
| `external_activity_detected` | Órdenes en BingX con clientOrderID no registrado |
| `our_client_order_ids` | Lista de IDs propios (últimos 20) para comparar |

Cuando `external_close_detected = True`:
- NO activa emergencia
- State se limpia automáticamente
- Robot espera siguiente señal TV
- El otro símbolo no se ve afectado

---

## SL Broker order IDs (#11)

Campos `sl_broker_order_id_long` y `sl_broker_order_id_short` en `positions[symbol]`:

- Se guardan tras crear un STOP_MARKET exitoso
- Se usan para cancelar el STOP anterior antes de crear uno nuevo
- Se limpian en `update_position()` al cerrar la posición
- Si son None → no hay STOP activo → se crea directamente

---

## Persistencia

| Situación | Comportamiento |
|---|---|
| Reinicio por inactividad (Render free) | State restaurado desde /tmp ✅ |
| Deploy nuevo | /tmp borrado → state desde cero ⚠️ |
| Crash inesperado | State restaurado desde /tmp si existe ✅ |
| BD real (#12) | Fix definitivo — PostgreSQL sin pérdida ❌ pendiente |

---

## Limitaciones conocidas

- `/tmp` se borra en cada deploy → fix en #12 BD real
- State global por proceso → multi-usuario requiere `state[user_id][symbol]` (#12b)
- Campos legacy se eliminarán cuando multi-symbol esté 100% estable

---
## Sesión 6 — Emergency por robot

### Campo nuevo en _state
```python
"emergency_by_robot": {}  # {robot: {"active": bool, "reason": str}}
```
Se inicializa vacío si no existe en disco (migración limpia).

### Funciones nuevas
- `set_robot_emergency(robot, active, reason)` — activa/desactiva + sync legacy
- `get_robot_emergency(robot)` — devuelve `{"active": bool, "reason": str}`
- `is_any_emergency()` — True si cualquier robot en emergency

### Sync legacy automático
Cuando se llama `set_robot_emergency`:
- `emergency = True` si cualquier robot activo
- `blocked = True` si cualquier robot activo
- `emergency_reason` = razón del robot activo


