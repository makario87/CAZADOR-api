# Arquitectura del Sistema
**Versión: v7 | Sesión 5**

---

## Flujo completo

```
TradingView
  │ Pine Script v6 detecta señal
  │ Construye JSON con signal, symbol, price, time, token,
  │ pyramid_max, pyramid_current, sl_broker
  │
  ↓ HTTP POST (webhook)
  │
Flask — routes/webhook.py
  │ Valida token de autenticación
  │ Comprueba expiración de señal (SIGNAL_EXPIRY_SECONDS)
  │ Loguea señal recibida
  │ Encola en QueueManager
  │
  ↓ Cola thread-safe
  │
QueueManager — core/queue_manager.py
  │ Procesa señales en orden FIFO
  │ Thread-safe — sin race conditions
  │
  ↓
SignalHandler — core/signal_handler.py
  │ Valida señal (VALID_SIGNALS)
  │ Control pirámide (pyramid_current vs pyramid_max)
  │ Anti-duplicados (bar_time por símbolo)
  │ Control emergencia (bloquea o deja pasar)
  │ Dispatcha a función específica
  │
  ↓ según señal
  │
  ├─ ENTRY_LONG/SHORT  → calcula qty → place_order() → _send_sl_broker()
  ├─ CLOSE_LONG/SHORT  → close_all_positions()
  ├─ GIRO_LONG/SHORT   → close + sleep + open → _send_sl_broker()
  └─ SL_*              → close_all_positions()
  │
  ↓ BingX API — brokers/bingx.py
  │ Firma HMAC SHA256
  │ POST /openApi/swap/v2/trade/order
  │ Retry automático (hasta 3 intentos)
  │
  ↓ BingX ejecuta orden
  │
State — data/state.py
  Actualiza positions[symbol]
  Persiste en /tmp/cazador_state.json
```

---

## Arquitectura PANEL ↔ CENTRAL (futura)

```
PANEL (Render free — puede dormirse)
  → solo UX: formularios, dashboards, configuración visual
  → POST /user/config → CENTRAL

CENTRAL (Render paid — siempre activo)
  → guarda config persistente en BD (PostgreSQL)
  → ejecuta trading 24/7
  → reconciler, emergency, watchdog
  → websockets automáticos 24/7
  → proxies por usuario
  → conexiones BingX
  → estado bots
```

Regla de oro: si PANEL se duerme → CENTRAL sigue funcionando solo.

---

## Arquitectura multi-robot (futura)

```
TradingView (1 alerta por estrategia/robot)
    ↓ webhook con token maestro por robot
CENTRAL identifica robot → busca usuarios suscritos activos
    ↓ replica orden individualmente por usuario
BingX usuario 1, BingX usuario 2, BingX usuario 3...
    ↓
Panel actualiza estados + Telegram alertas individuales
```

---

## Separación de responsabilidades

| Capa | Responsabilidad | NO hace |
|---|---|---|
| TradingView | Decide entradas, SL, giros | No ejecuta órdenes |
| Python | Ejecuta, gestiona estado | No decide estrategia |
| BingX | Ejecuta órdenes reales | SL broker solo airbag |
| Panel | UX, configuración visual | No ejecuta trading |

---

## Archivos principales

```
/app.py                    Flask + endpoints + sincronización arranque
/routes/webhook.py         Recibe señales TV + log señales expiradas
/core/signal_handler.py    Interpreta y ejecuta señales
/core/reconciler.py        Verifica estado Python vs BingX
/core/emergency.py         Modo emergencia + watchdog BingX
/core/queue_manager.py     Cola thread-safe
/brokers/bingx.py          Conexión API BingX HMAC SHA256
/brokers/market_info.py    Contratos, precision, min_qty, caché 1h
/data/state.py             Estado persistente JSON /tmp
/data/trade_log.py         Historial persistente CSV /tmp
/logs/logger.py            Logs consola + archivo /tmp rotación diaria
/utils/auth.py             Validación token webhook
/utils/time_utils.py       Helpers tiempo
/reports/csv_exporter.py   Exportar CSV
/config/settings.py        Variables entorno
```

## Sesión 7 — BD SQLite introducida

### Stack actualizado
TradingView → Webhook → Python Middleware (Render) → BingX API
                                     ↓
                              SQLite (cazador.db)

### Archivo nuevo
`data/database.py` — inicialización SQLite, schema completo, helpers genéricos.

### Tablas creadas
- robots, users, api_keys, subscriptions, configs, trades, system_state, proxies

### Qué migró
- `data/trade_log.py` → trades persistentes en SQLite (antes CSV en /tmp)

### Qué sigue pendiente
- `data/state.py` → sigue en RAM + /tmp JSON (próxima sesión)

## Sesión 7 — Decisión arquitectónica: subcuenta dedicada obligatoria

### Filosofía
El usuario NO conecta su cuenta principal BingX.
Conecta una subcuenta exclusiva para uso del bot.
Esa subcuenta debe usarse únicamente para trading automático CAZADOR.

### Ventajas arquitectónicas
- Aislamiento total del capital automatizado
- Reconciler fiable — cualquier posición no registrada es anomalía, no ambigüedad
- Política de huérfanas puede ser más agresiva con menos riesgo
- Kill switch más seguro
- Auditoría y routing más claros
- Menos soporte y debugging

### Impacto en política de huérfanas
Con subcuenta dedicada, una posición no registrada por Python
ya no es "el usuario tocó algo" — es siempre desync serio, bug,
intervención externa u operación residual.
Política futura válida: alerta fuerte + bloqueo temporal + revisión obligatoria.

### Política QA/desarrollo
- Todas las pruebas en DEMO sobre entorno propio del creador
- Nunca sobre usuarios reales
- Nunca mezclando entornos live de clientes
- Impacto de errores de desarrollo aislado al entorno demo del creador

### Pendiente verificar antes de live
- Subcuentas BingX soportan hedge mode
- Permisos API correctos en subcuenta
- Transferencias de fondos entre cuenta principal y subcuenta
- Límites y restricciones BingX en subcuentas

### Pirámide por usuario (#12e) — sesión 10

**Filosofía definitiva:**
- TV = cerebro matemático (genera señales, calcula SL, gestiona su pirámide interna)
- Python = risk manager (decide si ejecuta según config usuario, controla exposición real)
- BingX = verdad absoluta (existencia de posición)

**Reglas:**
- Python ignora pyramid_current y pyramid_max del payload de TV
- has_open_position(symbol, side) consulta BingX real — retorna 1/0/-1
- Si BingX dice 0 → reset_pyramid() → contador interno a 0
- Si BingX dice 1 → usar contador interno Python
- Si pyramid_count >= PYRAMID_MAX_DEFAULT → BLOQUEADO
- Si bloqueado: SL broker se refresca igualmente (TV sigue siendo válido matemáticamente)
- GIRO nunca bloqueado por pirámide

**Transición config:**
- Ahora: PYRAMID_MAX_DEFAULT en variable de entorno Render
- Futuro: subscriptions.pyramid_max por usuario+robot (cuando llegue panel)

**BingX Hedge Mode — limitación:**
- BingX NO cuenta entradas individuales — acumula qty en una sola posición por lado
- El contador lógico de entradas vive únicamente en Python (state interno)
- has_open_position() solo detecta existencia — nunca cuenta entradas

### SL zombie — regla definitiva — sesión 10

- _entry_long(): cancela SL SHORT zombie antes de colocar SL LONG (solo si code==0)
- _entry_short(): cancela SL LONG zombie antes de colocar SL SHORT (solo si code==0)
- _giro_long(): cancela SL SHORT zombie antes de abrir LONG (tras sleep buffer)
- _giro_short(): cancela SL LONG zombie antes de abrir SHORT (tras sleep buffer)
- app.py al arrancar: cancela en BingX real todos los SL order_ids guardados en state
- BingX 109400 (order not exist) es INFO, no WARNING

### Race condition reconciler/GIRO — sesión 10

- _giro_in_progress = {} en signal_handler.py (dict por user_id)
- _giro_long() y _giro_short() envueltos en try/finally: flag=True al inicio, flag=False en finally
- reconciler._check_state(): si any(_giro_in_progress.values()) → pausa y return
- El flag se libera siempre en finally — incluso si hay excepción en el GIRO
