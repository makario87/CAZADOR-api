# Deployment e Infraestructura
**Versión: v7 | Sesión 5**

---

## Stack de infraestructura

| Servicio | Uso | Plan |
|---|---|---|
| Render | Hosting Python/Flask | Free (CENTRAL futuro: paid) |
| GitHub | Repo + deploy automático | Free |
| UptimeRobot | Keepalive cada 5min | Free |
| BingX VST | Broker demo | Demo |
| BingX Live | Broker real | Live (futuro) |

---

## URLs

```
CENTRAL: https://central-bots-api-1.onrender.com
BingX Demo: https://open-api-vst.bingx.com
BingX Live: https://open-api.bingx.com
```

---

## Variables de entorno en Render

```
BINGX_API_KEY          = [key VST configurada]
BINGX_API_SECRET       = [secret VST configurado]
WEBHOOK_SECRET_TOKEN   = [token webhook configurado]
SIMULATION_MODE        = false
BINGX_ENV              = demo
RISK_PCT_DEFAULT       = 0.001   (0.1% del balance por entrada)
ORDER_TIMEOUT          = 10      (segundos timeout BingX)
PYRAMID_MAX_DEFAULT    = 3
GIRO_BUFFER_SECONDS    = 0.3     (pausa entre cierre y apertura en GIRO)
SIGNAL_EXPIRY_SECONDS  = 30      (señales más antiguas se ignoran)
```

---

## Deploy automático

```
Push a GitHub main
    ↓
Render detecta cambio
    ↓
Build automático
    ↓
Deploy (reinicia servicio)
    ↓ ⚠️ /tmp se borra aquí
Arranque: load_state() + sincronización BingX
```

---

## Keepalive UptimeRobot

Render free duerme el servicio tras 15min de inactividad.
UptimeRobot hace ping cada 5min al endpoint `/ping`:
```
GET https://central-bots-api-1.onrender.com/ping
→ {"status": "ok", "pong": true}
```

---

## Endpoints disponibles

| Endpoint | Método | Descripción |
|---|---|---|
| `/ping` | GET | Keepalive UptimeRobot |
| `/health` | GET | Estado completo del sistema |
| `/webhook` | POST | Recibe señales de TradingView |
| `/reset` | POST | Reset estado (requiere auth) |
| `/trades` | GET | Historial trades CSV |
| `/logs` | GET | Descarga cazador.log |

---

## Logs

```
Consola Render:   visible en dashboard (puede truncarse visualmente en free)
Archivo:          /tmp/cazador.log (rotación diaria)
Descarga:         GET /logs
```

Truncado visual en Render free: solo afecta a la visualización,
NO afecta ejecución real de órdenes ni estado interno.

---

## Persistencia actual (limitada)

```
/tmp/cazador_state.json  ← state del sistema
/tmp/cazador_trades.csv  ← historial trades
/tmp/cazador.log         ← logs rotativos
```

⚠️ Todo se borra en cada deploy. Fix en #12 BD real.

---

## Configuración manual en BingX

Antes de operar en un nuevo símbolo:
1. Activar Hedge Mode en BingX (por símbolo)
2. Configurar leverage manualmente en BingX (por símbolo)
3. Configurar Margin Mode: ISOLATED

Python NO valida leverage/margin actualmente (#11b pendiente).

---

## Checklist antes de live

```
✅ BingX Hedge Mode activado
✅ Leverage configurado manualmente
✅ Margin Mode: ISOLATED
✅ API keys configuradas en Render
✅ WEBHOOK_SECRET_TOKEN configurado en Render y Pine
✅ SIMULATION_MODE = false
✅ BINGX_ENV = demo (cambiar a live cuando llegue #18)
✅ UptimeRobot activo
✅ Pine Script: token correcto en input
✅ Pine Script: alert configurada con webhook URL
❌ #18 Live capital real → solo después de #12+#17+#16+#11b
```

---

## Arquitectura futura (infraestructura)

```
CENTRAL (Render paid — siempre activo)
  → BD PostgreSQL persistente
  → WebSocket privado por cuenta BingX (automático)
  → Proxies dedicados por usuario (~2€/mes por IP)
  → Workers background (reconciler por usuario)
  → Rate limiting escalonado

PANEL (Render free — puede dormirse)
  → Solo UX — consume API de CENTRAL
  → Si se duerme → CENTRAL sigue solo
```

## Sesión 11 — Panel MVP desplegado

### Nuevo servicio — central-bots-panel
- Tipo: Static Site en Render
- Repo: central-bots-panel (GitHub)
- Deploy automático en push a main
- No requiere variables de entorno — PANEL_SECRET_TOKEN lo introduce el admin en login
- URL: https://central-bots-panel.onrender.com

### central-bots-api-1 — cambios sesión 11
- flask-cors añadido a requirements.txt
- CORS habilitado solo para /panel/* con origen restringido al panel
- PANEL_SECRET_TOKEN añadido como variable de entorno en Render
- Blueprint panel_bp registrado en app.py
- panel_api.py añadido en /routes/

### Estructura repo central-bots-panel
index.html      → portada con login
panel.html      → panel de control
config.js       → URL base del middleware (apunta a central-bots-api-1)
js/auth.js      → lógica login y validación contra middleware
js/panel.js     → lógica panel — carga status, users, alerts cada 30s
