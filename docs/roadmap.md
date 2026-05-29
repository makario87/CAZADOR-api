# Roadmap — Plan Completo v7
**Versión: v7 | Sesión 5 | 2026-05-26**

---

## Estado actual

```
✅ #1  Retry automático BingX
✅ #2  Log a archivo /tmp
✅ #3  Detección cierre externo
✅ #4  Huérfanas — detección básica
✅ #5  Watchdog BingX
✅ #6  Health check mejorado
✅ #9  State multi-símbolo
✅ #9b Bug pirámide aditiva
✅ #11 SL broker automático BingX
⚠️ #7  Emergencia por robot → hasta #12 BD
⚠️ #8  Tokens por robot → token maestro por estrategia
❌ #12 BD real ← PRÓXIMA SESIÓN
❌ #16 Panel web
❌ #17 Multi-usuario
❌ #18 Live capital real
```

---

## 🔴 PRIORIDAD ALTA — Infraestructura SaaS (antes del panel)

### #12 BD real (SQLite → PostgreSQL)
Prerequisito absoluto de todo lo demás.
- /tmp inaceptable con clientes reales
- Tablas: users, bots, subscriptions, configs, trades, api_keys, proxies
- Schema multi-robot desde el inicio (bot_id, strategy_id)
- Sesión 6

### #12b State multi-usuario
- `state[user_id][symbol]` — aislamiento real entre usuarios
- Sin tocar signal_handler (capa de abstracción)
- Sesión 7

### #12c Cola por usuario
- `queue[user_id]` — sin bloqueo cruzado entre usuarios
- Señal lenta de usuario A no bloquea a usuario B
- Sesión 7

### #12d Auditoría trades en BD
- Tabla trades: user_id, bot_id, symbol, side, qty, price, pnl, signal, timestamp
- Requisito legal para cobrar % sobre beneficios
- Sesión 8

### #17a Delays escalonados
- Implementar antes del 2º usuario real simultáneo
- 5 usuarios × polling 30s × operaciones ≈ 75-100 calls/min → bloqueo BingX
- Sesión 8

### #17b Proxies por usuario
- IP fija por API key (~2€/mes por proxy, tarifa plana)
- Arquitectura: Render → proxy dedicado usuario X → BingX
- CENTRAL gestiona proxies, no el panel
- 10 usuarios = ~20€/mes adicionales, coste fijo
- Sesión 9

### #17c Reconciler por usuario
- Reconciler independiente por usuario
- Sin contaminación cruzada
- Sesión 9

---

## 🟡 PRIORIDAD MEDIA — Multi-usuario + observabilidad

### #17 Multi-usuario completo
Requiere #12 + #17a + #17b + #17c
- Token maestro por estrategia/robot → routing interno
- Ejecución paralela por usuario suscrito
- Aislamiento completo entre usuarios
- Sesión 10

### #16 Panel web
Requiere #12 + #17 completos.
DESPUÉS de que CENTRAL tenga todos los endpoints.
- Solo UX encima de base sólida
- Cada botón tiene su endpoint ya existente
- Vista proveedor: todos robots, todos clientes
- Posiciones abiertas + PnL por símbolo
- Configuración por usuario: leverage, risk_pct, balance ref
- Acciones remotas: restablecer, cerrar, pausar
- Estado WebSocket: conectado/latencia/último ping
- Estado proxy por usuario
- Flags: external_close_detected, external_activity_detected
- Sesiones 11-12

### #11b Validación pre-orden
Requiere #16 panel (config por usuario).
- Leverage esperado vs BingX real → bloquea + alerta si no coincide
- Margin mode esperado → bloquea + alerta
- Hedge mode esperado → bloquea + alerta
- Balance dentro de rango → warning flexible
- Sesión 13

### #10 Telegram
- Notificaciones al proveedor: operaciones, rechazos, emergencias
- Bot privado por cliente con botones: [RESTABLECER] [CERRAR TODO] [PAUSAR]
- Canal global solo proveedor
- Sesión 14

---

## 🔵 PRIORIDAD BAJA

```
#13  Reporting completo
#14  Reconciliador avanzado
#15  Backup state antes de deploy
#18  Live capital real mínimo
     Solo después de #12+#17+#16+#11b completados y validados
```

---

## Orden de sesiones

```
Sesión 6  → #12 BD real — SQLite primero, schema completo multi-robot
Sesión 7  → #12b+#12c state y cola multi-usuario
Sesión 8  → #12d auditoría trades + #17a delays escalonados
Sesión 9  → #17b proxies + #17c reconciler por usuario
Sesión 10 → #17 multi-usuario completo
Sesión 11 → #16 panel básico (encima de base sólida)
Sesión 12 → #16 panel completo
Sesión 13 → #11b validación pre-orden
Sesión 14 → #10 Telegram
Sesión 15 → #18 live capital real mínimo
```

---

## Huecos arquitectónicos identificados

### 🔴 Críticos antes de multi-usuario
- BD real — /tmp inaceptable con clientes reales
- Aislamiento state por usuario — hoy state es global
- Cola por usuario — hoy cola global bloquea entre usuarios
- Rate limit BingX multi-cuenta
- Proxies por usuario — misma IP para todos es riesgo

### 🟡 Importantes no bloqueantes inmediatos
- Separación API / Trading Engine (Flask + worker separado)
- Workers/background jobs robustos
- Recuperación cola tras crash
- Almacenamiento cifrado API keys
- Health checks por usuario
- Límites por usuario (plan, max_symbols, risk%)

### 🔵 Escalado futuro
- WebSocket multi-cuenta (trigger: rate limit real o +10 usuarios)
- Separación microservicios

---

## Schema BD multi-robot (sesión 6)

```sql
robots
  id, name, token_maestro, description, active

users
  id, name, email, telegram_id, active, plan

subscriptions
  id, user_id, robot_id, active, risk_pct,
  leverage, capital_pct, proxy_id

api_keys
  id, user_id, exchange, key_encrypted,
  secret_encrypted, env (demo/live)

configs
  id, user_id, robot_id, symbol,
  params (JSON), updated_at

trades
  id, user_id, robot_id, symbol, side,
  qty, price, pnl, signal, timestamp

proxies
  id, user_id, ip, port, active
```

Regla de diseño: toda tabla crítica lleva `robot_id` + `user_id` desde el día 1.

---

## Modelo de negocio

```
200€ setup por cliente (onboarding, configuración TV + BingX)
20% anual sobre beneficios del robot
Extractos individuales por cliente (tabla trades en BD)
Canal Telegram global (solo proveedor escribe)
Bot Telegram privado por cliente con botones de acción
```

---

## Bugs conocidos

```
⚠️ /tmp se borra en cada deploy → fix en #12
⚠️ Bug triángulo negro misma vela apertura → rarísimo con filtros, dejar
⚠️ Logs Render free truncados visualmente → no afecta ejecución
```

---

## Deuda técnica documentada

```
signal_handler.py: price = payload.get("price","0") → normalizar a float
Log POST payload verbose → bajar a DEBUG cuando estable
timezone configurable en /trades y /health (UTC+2 España)
Pine Script: eliminar input ROBOT_NAME cuando llegue #17
Pine Script: token maestro por estrategia cuando llegue #17
logger.py: archivo separado por robot cuando llegue #17
/logs endpoint en panel para descargar log sin Shell Render
Campos legacy state.py → limpiar cuando multi-symbol 100% estable
external_close_detected → separar en 3 flags granulares con panel/BD
WebSockets privados BingX → implementar cuando trigger real (+10 usuarios)
Delays escalonados cola → implementar antes del 2º usuario real
```
## Sesión 7 — #12 BD real (parcial)

### Completado
- ✅ data/database.py — schema SQLite completo, 8 tablas, idempotente
- ✅ data/trade_log.py — migrado de CSV /tmp a SQLite
- ✅ init_db() integrado en app.py antes de load_state()/load_trades()
- ✅ QA: /health OK, /trades OK, trades persistentes en BD

### Bug detectado y resuelto
init_db() no se ejecutaba antes de load_trades() → OperationalError: no such table: trades
Fix: llamar init_db() explícitamente al arranque en app.py antes de load_state()

### Pendiente próxima sesión
- ❌ data/state.py → migrar RAM + /tmp JSON a SQLite (tabla system_state)

## Sesión 7 — #12 BD real (parcial) + replanteo prioridades

### Completado
- ✅ data/database.py — schema SQLite completo, 8 tablas, idempotente
- ✅ data/trade_log.py — migrado de CSV /tmp a SQLite
- ✅ data/state.py — migrado de /tmp JSON a SQLite
- ✅ init_db() integrado en app.py
- ✅ QA end-to-end: pirámide + giro validados con SQLite

### Replanteo de prioridades
Panel operativo adelantado — ya no es estética, es consola operativa necesaria antes de QA multiusuario real a distancia.

### Orden actualizado
```
Sesión 8  → #12b state multi-usuario
Sesión 9  → #12c cola por usuario
Sesión 10 → #12d auditoría trades + #17a delays
Sesión 11 → Panel MVP operativo
Sesión 12 → Fase 3: tú + padre DEMO simultáneos con panel
```

## Sesión 8 — #12b + #12c Multi-usuario base implementado

### #12b — State multi-usuario
- `_states[user_id]` en vez de `_state` global
- `DEFAULT_USER = "default"` como puente de compatibilidad
- Todas las funciones públicas aceptan `user_id=DEFAULT_USER`
- `save_state(user_id)` → key `state:<user_id>` en SQLite
- `load_state()` migra automáticamente legacy `key='main'` → `state:default`
- `get_all_user_ids()` nuevo helper para reconciler y panel

### #12c — Cola multi-usuario
- `_queues[user_id]` + `_workers[user_id]` en queue_manager
- `enqueue(payload, user_id)` — sin bloqueo cruzado entre usuarios
- `user_id` propagado desde webhook → payload → signal_handler → state
- Webhook asigna `user_id="default"` — futuro: lookup en BD por token/robot
- `queue_size_all()` nuevo helper para panel

### Bugs encontrados y resueltos
- `/health` usaba `_worker` legacy → migrado a `_workers[DEFAULT_USER]`
- `start_worker` faltaba en imports tras refactor
- Import legacy `_worker` dentro de `def health()` — eliminado

### QA
- Deploy verde, /health OK
- worker_alive, reconciler_alive, watchdog_alive: true
- Arquitectura multi-usuario base operativa sobre DEFAULT_USER

## Sesión 9 — #12d + ruta interna QA

### Completado
- ✅ #12d auditoría trades con user_id — TEXT NOT NULL, fallo ruidoso
- ✅ Fix FK: trades.user_id TEXT NOT NULL — sin referencia a users.id
- ✅ Ruta interna /internal/test-signal — QA multi-activo validado
- ✅ Fase 2 completada — multi-símbolo DEMO validado (PENGU + SOL)

### Orden actualizado
- Sesión 10 → #17a delays escalonados + reconciler por usuario
- Sesión 11 → Panel MVP operativo
- Sesión 12 → Fase 3: tú + padre DEMO simultáneos con panel

## Sesión 11 — Roadmap actualizado v12

### Orden sesiones actualizado
Sesión 12 → Módulo usuarios + API keys cifradas + audit_log
Sesión 13 → Alertas críticas + Telegram
Sesión 14 → Panel módulo usuarios completo + balance BingX
Sesión 15 → Fase 3 — tú + padre DEMO con panel completo
Sesión 16 → PostgreSQL + backup BD
Sesión 17 → Cloudflare + hardening seguridad
Sesión 18 → Proxies + WebSocket
Sesión 19 → Validación final multiusuario — romper en DEMO
Sesión 20 → LIVE mínimo — solo tú, capital mínimo real

### #17a delays escalonados — POSPUESTO indefinidamente
- Es parche para Render free tier + HTTP polling
- Solución definitiva es WebSocket
- Sin evidencia de problema real en logs
- Se revisa solo si aparece evidencia concreta antes de llegar a WebSocket

### Filosofía de construcción hasta LIVE
1. Robustez
2. Trazabilidad
3. Monitorización
4. Seguridad
5. Escalabilidad
El rediseño visual y estadísticas avanzadas van después de todo lo anterior.
