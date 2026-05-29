# security.md
Seguridad webhook — CAZADOR Middleware

## Filosofía
Seguridad por capas ahora. Seguridad fuerte de infraestructura antes de escalar clientes reales.
Fail Closed: cualquier fallo crítico de seguridad activa Emergency Mode para ese robot.
Mejor parar que ejecutar órdenes potencialmente comprometidas.

---

## Capas implementadas

### Capa 2 — Token secreto ✅
- Comparación `hmac.compare_digest` — timing-safe
- Token en header `X-Webhook-Token` o campo `token` en body
- Fallo → 401 + Emergency Mode

### Capa 3 — Schema validation ✅ (sesión 6)
- Campos obligatorios: `signal`, `robot`, `symbol`, `tf`, `price`, `time`, `token`
- Fallo → 400 + Emergency Mode
- Implementado en `utils/security.py` → `validate_schema()`

### Capa 4 — Timestamp expiry ✅
- Señales antiguas descartadas silenciosamente
- NO activa Emergency
- Configurable: `SIGNAL_EXPIRY_SECONDS`

### Capa 5 — Anti-duplicados ✅ (sesión 6)
- Hash: `robot + symbol + signal + time[:16]`
- Ventana: `DEDUP_WINDOW_SEC = 5s`
- NO activa Emergency — puede ser retry legítimo
- Implementado en `utils/security.py` → `validate_no_duplicate()`

---

## Capas pospuestas — implementar con Cloudflare

### Capa 1 — IP whitelist TradingView ⏳
IPs oficiales TV:
```
52.89.214.238
34.212.75.30
54.218.53.128
52.32.178.7
```
⚠️ LIMITACIÓN: `X-Forwarded-For` en Render directo es falsificable por cualquier atacante.
Esta capa sería DISUASORIA/OPERATIVA, no criptográficamente confiable.
Implementar solo cuando Cloudflare esté delante usando `CF-Connecting-IP`.

### Capa 6 — Rate limit ⏳
Cloudflare lo hará mejor con WAF y reglas configurables.
Evitar sobreingeniería en Flask.

---

## Objetivo obligatorio antes de live serio — Cloudflare

```
Cloudflare delante de Render
  → solo aceptar tráfico desde Cloudflare
  → usar CF-Connecting-IP como IP real confiable (infalsificable)
  → WAF + rate limits en Cloudflare
  → Render inaccesible públicamente excepto vía Cloudflare
  → IP whitelist TradingView confiable
```

---

## Qué activa Emergency Mode

| Causa | Emergency | Código |
|---|---|---|
| Token inválido | ✅ Sí | 401 |
| Schema inválido | ✅ Sí | 400 |
| Señal duplicada | ❌ No | 409 |
| Timestamp expiry | ❌ No | 200 |
| IP no autorizada | ⏳ Pospuesto | — |
| Rate limit | ⏳ Pospuesto | — |
| BingX sin respuesta | ✅ Sí (watchdog) | — |

---

## BD — API keys cifradas (implementar en #12)

```
API keys → AES-256 cifradas en PostgreSQL
NUNCA en texto plano
NUNCA en variables de entorno
Una sola variable crítica en Render: MASTER_ENCRYPTION_KEY
CENTRAL descifra en memoria solo al ejecutar orden
Descarta de memoria inmediatamente después
Panel nunca muestra keys en claro — solo últimos 4 caracteres
```

---

## Decisión futura — Emergency robot vs robot+symbol

Aislamiento actual: por `robot`.
Si falla CAZADOR+PEPE → caen todos los símbolos de CAZADOR.

Mejora futura: aislamiento por `robot+symbol`.
- Si cae PEPE → BTC sigue vivo
- Resiliencia mayor en SaaS multi-activo

Estado: pospuesto. Evolución para fase SaaS real multi-usuario.

---

## Archivos relevantes

```
utils/security.py     validate_schema() + validate_no_duplicate()
utils/auth.py         validate_webhook_token()
utils/time_utils.py   is_signal_expired()
routes/webhook.py     orquesta todas las capas
core/emergency.py     activate_emergency() + trigger_emergency()
config/settings.py    WEBHOOK_REQUIRED_FIELDS, DEDUP_WINDOW_SEC
```

## Sesión 9 — Ruta interna QA + rotación tokens

### /internal/test-signal
- Token exclusivo: INTERNAL_TEST_TOKEN en Render — independiente de WEBHOOK_SECRET_TOKEN
- Header: X-Internal-Token
- Salta: timestamp expiry, anti-duplicados, schema TV estricto
- NO salta: queue, signal_handler, state, trade_log, BD, BingX
- 503 si INTERNAL_TEST_TOKEN no configurado en Render
- Logs marcados con [TEST] para distinguir de señales reales
- Nunca documentar ni exponer públicamente

### Tokens rotados
- WEBHOOK_SECRET_TOKEN rotado — TradingView actualizado
- INTERNAL_TEST_TOKEN configurado nuevo en Render

## Sesión 11 — Panel MVP + token MASKED

### Token webhook MASKED en logs
- RAW BODY loguea token enmascarado con regex antes de escribir en log
- JSON PARSED loguea safe_payload con token="MASKED"
- El token nunca aparece en logs de Render en ningún formato
- Aplica a todas las señales recibidas por el webhook

### Panel MVP — seguridad
- PANEL_SECRET_TOKEN en Render — nunca en código ni en GitHub
- Header X-Panel-Token obligatorio en todos los endpoints /panel/*
- Sin token válido → 401 inmediato sin datos
- CORS restringido exclusivamente a https://central-bots-panel.onrender.com
- Webhook no necesita CORS — es server-to-server, no navegador
- sessionStorage MVP — deuda técnica: cookies httpOnly + sesiones server-side en iteración futura

### Norma permanente del proyecto
- GitHub contiene únicamente código y documentación
- Ningún dato real de clientes en GitHub bajo ningún concepto
- Usuarios, API Keys, saldos, trades y estados viven exclusivamente en BD
- API Keys se almacenarán cifradas AES-256 — implementar en sesión 12
- Ningún secret aparece en logs — política MASKED obligatoria para todo el proyecto
