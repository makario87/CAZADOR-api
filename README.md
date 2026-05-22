# CAZADOR Middleware

TradingView → Webhook → Python → BingX API

## Arquitectura

```
CAZADOR (PineScript)
    ↓ Webhook
Python Middleware (Render)
    ↓ API REST
BingX
```

## Estructura

```
/app.py              ← arranque Flask
/routes/
    webhook.py       ← recibe señales TV
/core/
    signal_handler.py ← interpreta y ejecuta señales
    reconciler.py    ← verifica TV vs broker
    emergency.py     ← modo emergencia
    queue_manager.py ← cola de señales
/brokers/
    bingx.py         ← conexión API BingX
/data/
    state.py         ← estado global
    trade_log.py     ← registro operaciones
/logs/
    logger.py        ← sistema logs
/utils/
    auth.py          ← validación webhook token
    time_utils.py    ← helpers tiempo
/reports/
    csv_exporter.py  ← exportar CSV/Excel
/config/
    settings.py      ← variables entorno
```

## Variables de entorno (Render)

| Variable | Descripción |
|---|---|
| BINGX_API_KEY | API Key de BingX |
| BINGX_API_SECRET | API Secret de BingX |
| WEBHOOK_SECRET_TOKEN | Token secreto para validar webhooks |
| DEMO_MODE | true/false |

## Señales soportadas

- `ENTRY_LONG` / `ENTRY_SHORT`
- `CLOSE_LONG` / `CLOSE_SHORT`
- `GIRO_LONG` / `GIRO_SHORT`
- `SL_LONG_DYNAMIC` / `SL_SHORT_DYNAMIC`
- `SL_LONG_BLACK` / `SL_SHORT_BLACK`
- `SL_LONG_CCI` / `SL_SHORT_CCI`
- `SL_LONG_PROMEDIO` / `SL_SHORT_PROMEDIO`

## Endpoints panel

| Endpoint | Descripción |
|---|---|
| GET / | Panel estado |
| GET /ping | Keep alive |
| GET /state | Estado completo |
| GET /balance | Balance BingX |
| GET /positions | Posiciones abiertas |
| GET /trades | Historial operaciones |
| GET /trades/csv | Exportar CSV |
| POST /emergency/resolve | Resolver emergencia |
| POST /reset | Reset estado |
| POST /webhook | Recibir señales TV |

## Header requerido en TradingView

```
X-Webhook-Token: <tu_token_secreto>
```
