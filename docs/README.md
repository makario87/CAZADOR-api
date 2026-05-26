# PROYECTO CAZADOR — Documentación Técnica
**Versión: v7 | Última actualización: sesión 5 | 2026-05-26**

---

## ¿Qué es CAZADOR?

CAZADOR es un sistema de trading algorítmico automatizado que opera futuros perpetuos en BingX.
Está compuesto por tres capas:

```
TradingView (cerebro estratégico)
    ↓ webhook JSON
Python Middleware — central-bots-api (ejecución y gestión)
    ↓ REST API
BingX (broker — ejecución real de órdenes)
```

---

## Stack tecnológico

| Componente | Tecnología |
|---|---|
| Estrategia | Pine Script v6 en TradingView |
| Backend | Python 3 + Flask |
| Hosting | Render (free/paid) |
| Broker | BingX Perpetual Futures (Hedge Mode) |
| BD actual | /tmp JSON + CSV (temporal) |
| BD futura | SQLite → PostgreSQL |
| Keepalive | UptimeRobot → /ping cada 5min |
| Repo | GitHub (deploy automático en Render) |

---

## Robots actuales y futuros

| Robot | Token maestro | Estado |
|---|---|---|
| CAZADOR | MASTER_CA | ✅ activo |
| DRAGON | MASTER_DR | ❌ pendiente |
| SNIPER | MASTER_SN | ❌ pendiente |

---

## Entornos

| Entorno | URL BingX | Variable |
|---|---|---|
| Demo VST | open-api-vst.bingx.com | BINGX_ENV=demo |
| Live | open-api.bingx.com | BINGX_ENV=live |

---

## Documentación disponible

| Archivo | Contenido |
|---|---|
| `architecture.md` | Flujo completo TradingView → BingX |
| `state.md` | Sistema de estado, multi-symbol, persistencia |
| `broker_layer.md` | BingX API, normalización, retry, órdenes |
| `signals.md` | Todas las señales y su flujo de ejecución |
| `pyramid.md` | Pirámide, anti-duplicados, GIROS |
| `reconciler.md` | Reconciliador, detección externa, huérfanas |
| `emergency.md` | Modo emergencia, watchdog, protección |
| `sl_system.md` | Todos los SL + SL broker airbag |
| `roadmap.md` | Plan completo v7 + decisiones arquitectónicas |
| `deployment.md` | Infra, variables de entorno, UptimeRobot |
| `troubleshooting.md` | Bugs conocidos, casos edge, validaciones |

---

## Filosofía core

- **TV es el cerebro** — decide estrategia, calcula SL, decide entradas
- **Python ejecuta** — no decide estrategia, solo ejecuta y gestiona estado
- **BingX es el broker** — ejecuta órdenes, SL broker solo como airbag
- **Crecer sin rehacer** — capas desacopladas desde el principio
- **State no miente** — nunca actualiza si BingX falla
- **Emergencia blindada** — SL/CLOSE/GIRO nunca se bloquean
