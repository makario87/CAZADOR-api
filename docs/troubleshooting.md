# Troubleshooting — Bugs y Casos Edge
**Versión: v7 | Sesión 5**

---

## Bugs conocidos activos

### ⚠️ /tmp se borra en cada deploy
**Problema:** state.json y trades.csv en /tmp se pierden con cada deploy.
**Impacto:** estado del bot se resetea, historial trades se pierde.
**Fix:** #12 BD real (PostgreSQL).
**Workaround actual:** sincronización con BingX al arrancar reconstruye posiciones.

### ⚠️ Logs Render free truncados visualmente
**Problema:** el tail de logs en Render free puede mostrar gaps visuales.
**Impacto:** NINGUNO en ejecución real. Solo visual.
**Confirmado:** TV sigue mandando alertas, BingX sigue ejecutando, reconciler sigue estable.
**Workaround:** descargar log completo desde `/logs` o Shell de Render.

### ⚠️ Bug triángulo negro en misma vela de apertura
**Problema:** en casos muy específicos puede aparecer señal negra en la misma vela de apertura.
**Impacto:** rarísimo con filtros EMA+ADX+CCI activos.
**Decisión:** dejar así — coste de fix > beneficio dado lo raro que es.

---

## Casos edge validados y resueltos

### Bug pirámide aditiva (#9b) — RESUELTO sesión 4
**Síntoma:** contador pirámide arrancaba en 0 tras GIRO.
**Causa:** `_giro_long/short()` no llamaban a `increment_pyramid()` ni `update_bar_time()`.
**Fix:** añadir ambas llamadas tras `update_entry()` en los dos GIROS.

### abs() en close_position() — RESUELTO
**Síntoma:** cierre SHORT fallaba con qty negativa.
**Causa:** BingX devuelve `positionAmt` negativo para SHORT.
**Fix:** `quantity = abs(float(pos.get("positionAmt", 0)))`.

### GIRO sin posición previa — VALIDADO
**Caso:** GIRO llega y BingX ya está plano (cerrado externamente).
**Comportamiento:** cierre devuelve `no_open_position` → GIRO abre directamente el nuevo lado.
**Resultado:** sin emergencia, sin bloqueo, robot continúa.

### external_close_detected sin emergencia — VALIDADO
**Caso:** reconciler detecta mismatch y setea `external_close_detected=True`.
**Comportamiento:** NO activa emergencia, state limpiado, robot sigue, otro símbolo no afectado.

### STOPs acumulados en pirámide — RESUELTO sesión 5 (#11)
**Síntoma:** nueva ENTRY creaba STOP nuevo pero el anterior seguía vivo en BingX.
**Causa:** no había lógica de cancelación del STOP previo.
**Fix:** flujo cancelar→crear con `cancel_order()` + `sl_broker_order_id` en state.

### BingX same-side fusion — DOCUMENTADO
**Confusión:** "Posiciones abiertas: 1" en BingX con 3 entradas de pirámide.
**Explicación:** Hedge Mode fusiona LONG+LONG en una línea acumulada. Normal.
**Validación real:** qty acumulada + reconciler + state + cierre correcto de golpe.

---

## Errores BingX comunes

| Code | Mensaje | Causa | Fix |
|---|---|---|---|
| 0 | OK | Éxito | — |
| 101500 | system busy | BingX saturado | Retry automático (ya implementado) |
| 109400 | timestamp invalid | Content-Type incorrecto o clock | POST sin Content-Type |
| -1 | no_open_position | Posición ya cerrada | Actualizar state igualmente |

---

## Diagnóstico rápido

### Robot no ejecuta órdenes
1. Verificar `SIMULATION_MODE` en Render (debe ser `false`)
2. Verificar `emergency` en `/health`
3. Verificar logs últimas señales recibidas
4. Verificar que Hedge Mode está activo en BingX

### State desincronizado con BingX
1. Verificar `last_reconciler_time` en `/health`
2. Revisar logs del reconciler
3. Si persiste: `/reset` + esperar siguiente señal TV

### Señales TV no llegan
1. Verificar UptimeRobot activo
2. Verificar webhook URL en Pine Script
3. Verificar `WEBHOOK_SECRET_TOKEN` coincide en Render y Pine
4. Verificar logs de expiración de señales

### STOP_MARKET no aparece en BingX
1. Verificar `useSL = true` en Pine
2. Verificar que `sl_broker` llega con valor > 0 en logs
3. Verificar logs de `_send_sl_broker()`
4. Si hay warning de rechazo → TV sigue gestionando SL normalmente

### Pirámide no incrementa correctamente
1. Verificar `pyramid_current` en JSON recibido (logs)
2. Verificar `pyramid_long_count` / `pyramid_short_count` en `/health`
3. Si hay desync: reconciler debería corregirlo en el siguiente ciclo

---

## Validaciones de arquitectura (por diseño, no requieren test)

| Caso | Validado por |
|---|---|
| SL broker falla → sin emergencia | Código: `_send_sl_broker()` nunca llama `trigger_emergency()` |
| ENTRY bloqueada en emergencia | Código: dispatcher bloquea todo excepto PROTECTION_SIGNALS |
| State no se actualiza si BingX falla | Código: `update_state()` solo se llama si `code == 0` |
| Anti-duplicados por vela | Código: comparación `bar_time + bar_tf` antes de ejecutar |
