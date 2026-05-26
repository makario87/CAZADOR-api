# Sistema de Emergencia
**Versión: v7 | Sesión 5**

---

## Filosofía

- **Emergencia no paraliza cierres** — las PROTECTION_SIGNALS siempre pasan
- **Emergencia sí paraliza entradas** — ENTRY_LONG/SHORT bloqueadas
- **State no miente** — si BingX falla, no actualizamos state
- **Retry de emergencia** — si orden falla (code != 0), se reintenta

---

## ¿Cuándo se activa la emergencia?

```python
trigger_emergency(reason: str)
```

Se llama desde `signal_handler.py` cuando:
- CLOSE/GIRO falla en BingX (código != 0 y no es no_open_position)
- GIRO cierra un lado pero no puede abrir el otro
- SL falla en BingX
- Excepción inesperada ejecutando cualquier señal

---

## Efecto de la emergencia

```python
state["emergency"]        = True
state["emergency_reason"] = reason
```

En el dispatcher de señales:
```python
if state.get("emergency"):
    if signal in PROTECTION_SIGNALS:
        # ejecutar igualmente — warning en logs
    else:
        # bloquear — return {"status": "blocked"}
```

---

## PROTECTION_SIGNALS — nunca bloqueadas

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

Garantiza que en cualquier escenario de fallo, TV puede cerrar posiciones.

---

## Watchdog BingX

Hilo background que verifica conectividad periódicamente:
```python
ping_bingx()  → GET /openApi/swap/v2/user/balance
```

- Si BingX no responde → loguea warning
- Si persiste → puede activar emergencia
- Si se recupera → loguea recuperación

---

## Reset de emergencia

Desde el endpoint `/reset` (panel o manual):
```python
reset_state()  → emergency = False
```

O desde el futuro panel con botón [RESTABLECER].

---

## SL broker y emergencia

`_send_sl_broker()` tiene su propio manejo de errores completamente independiente:
- Si BingX rechaza el STOP_MARKET → solo `logger.warning()`
- **Nunca llama a `trigger_emergency()`**
- Robot sigue operativo
- TV sigue siendo el gestor principal del SL

---

## Flags de estado en /health

```json
{
  "emergency": false,
  "emergency_reason": null,
  "blocked": false
}
```

---

## Casos validados

| Caso | Comportamiento |
|---|---|
| CLOSE falla en BingX | trigger_emergency — ENTRY bloqueadas |
| GIRO cierra pero no abre | trigger_emergency — queda flat |
| SL falla en BingX | trigger_emergency |
| CLOSE con no_open_position | NO emergencia — state limpiado |
| GIRO sin posición previa | NO emergencia — abre directamente |
| SL broker falla | NO emergencia — solo warning |
| external_close_detected | NO emergencia — state limpiado |
