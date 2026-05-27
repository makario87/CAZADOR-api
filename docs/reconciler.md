# Reconciliador
**Versión: v7 | Sesión 5**

---

## ¿Qué hace?

Verifica periódicamente que el estado interno de Python coincide con la realidad de BingX. Detecta discrepancias y las resuelve sin intervención manual.

---

## Cuándo corre

Hilo background independiente. Corre cada N segundos (configurable).
Registra timestamp en `state["last_reconciler_time"]`.

---

## Flujo principal

```
Para cada símbolo en positions[] con posición abierta:

1. Consultar posiciones reales en BingX (get_positions)
2. Comparar con state interno

Caso A: Python cree LONG, BingX no tiene LONG
  → external_close_detected = True
  → limpiar state del símbolo
  → robot espera siguiente señal TV

Caso B: Python cree SHORT, BingX no tiene SHORT
  → mismo flujo

Caso C: Python cree plano, BingX tiene posición
  → external_activity_detected = True
  → loguear como huérfana
  → no cerrar automáticamente (decisión del operador)

Caso D: Coinciden
  → todo OK, no hacer nada
```

---

## Detección de cierres externos

Cuando `external_close_detected = True`:
- **NO** activa modo emergencia
- State se limpia automáticamente para ese símbolo
- Robot sigue operativo
- Espera siguiente señal TV para ese símbolo
- El otro símbolo **no se ve afectado**

---

## Detección de huérfanas

Posiciones en BingX que Python no reconoce:
- Se loguean como `external_activity_detected`
- No se cierran automáticamente
- Requieren intervención manual o futura lógica de cierre

---

## Historial de órdenes

`get_order_history(symbol, limit=20)` — endpoint BingX:
```
GET /openApi/swap/v2/trade/allOrders
```

Compara `clientOrderID` de órdenes recientes con `our_client_order_ids` en state.
Si hay órdenes con ID desconocido → posible actividad externa.

---

## Multi-symbol

Reconciler itera sobre todos los símbolos en `positions[]`.
Cada símbolo se evalúa de forma independiente:
- Sin contaminación cruzada entre símbolos
- Cierre externo en BTC no afecta a PENGU
- Validado con BTC + PENGU simultáneos en ciclos largos

---

## Sincronización al arrancar

Al iniciar `app.py`, antes de empezar a recibir señales:
- Se consultan posiciones reales en BingX
- Se reconstruye `positions[]` en state
- Se sincronizan contadores de pirámide

Garantiza que un reinicio por inactividad (Render free) no desincroniza el estado.

---

## Estado del reconciler en /health

```json
{
  "last_reconciler_time": "2026-05-26T12:00:00",
  "external_close_detected": false,
  "external_activity_detected": false
}
```

## Sesión 7 — QA huérfanas tras migración SQLite

### Comportamiento observado
Durante pruebas/redeploys quedaron posiciones demo antiguas abiertas en BingX.
El reconciler reaccionó correctamente:
- Detectó DESYNC
- Detectó posición huérfana LONG BTC-USDT
- Marcó external_activity_detected=True
- NO cerró automáticamente — comportamiento conservador esperado
- Tras cierre manual en BingX: "Sin posiciones abiertas — estado sincronizado"

### Conclusión
Detección de huérfanas funciona correctamente tras migración SQLite y restart.

### Decisión arquitectónica pendiente — política de huérfanas (antes de live)
Casos reales: cierre manual en app móvil, botón accidental, otra API, desync broker.
Opciones a evaluar (no implementar ahora):
- Solo alertar (comportamiento actual)
- Bloqueo temporal del trading automático
- Reclaim/adoptar posición huérfana como propia
- Autoclose tras timeout configurable
- Validación extra antes de nueva entrada

Decisión: definir política antes de pasar a live con capital real.
