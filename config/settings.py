"""
config/settings.py
Carga todas las variables de entorno de forma centralizada.
NUNCA hardcodear claves aquí. Todo viene de Render Environment Variables.
"""
import os

# ============================================================
# 🔑 CREDENCIALES BINGX
# ============================================================
BINGX_API_KEY    = os.getenv("BINGX_API_KEY", "")
BINGX_API_SECRET = os.getenv("BINGX_API_SECRET", "")

# ============================================================
# 🔐 SEGURIDAD WEBHOOK — token principal
# ============================================================
WEBHOOK_SECRET_TOKEN = os.getenv("WEBHOOK_SECRET_TOKEN", "")

# --- FUTURO: tokens por robot (añadir cuando haya >1 robot) ---
# ROBOT_TOKENS = {
#     "CAZADOR_A": os.getenv("TOKEN_CAZADOR_A", ""),
#     "CAZADOR_B": os.getenv("TOKEN_CAZADOR_B", ""),
#     "HUNTER":    os.getenv("TOKEN_HUNTER",    ""),
# }

# ============================================================
# ⚙️ MODO OPERATIVO — DOS VARIABLES INDEPENDIENTES
# ============================================================

# SIMULATION_MODE: True  → órdenes simuladas en Python, NO van a BingX
#                  False → órdenes reales enviadas al broker
SIMULATION_MODE = os.getenv("SIMULATION_MODE", "true").lower() == "true"

# BINGX_ENV: "demo" → broker VST (open-api-vst.bingx.com)
#            "live" → broker real (open-api.bingx.com)
# Solo importa cuando SIMULATION_MODE=false
BINGX_ENV = os.getenv("BINGX_ENV", "demo").lower()

# DEMO_MODE: alias de compatibilidad — NO usar en código nuevo
# Permite que app.py y otros archivos no actualizados sigan funcionando
DEMO_MODE = SIMULATION_MODE

# ============================================================
# 🌐 ENDPOINTS BINGX
# ============================================================
_BINGX_BASE_URL_LIVE = "https://open-api.bingx.com"
_BINGX_BASE_URL_DEMO = "https://open-api-vst.bingx.com"

BINGX_BASE_URL = _BINGX_BASE_URL_LIVE if BINGX_ENV == "live" else _BINGX_BASE_URL_DEMO

# ============================================================
# ⏱️ CONFIGURACIÓN SISTEMA
# ============================================================
SIGNAL_EXPIRY_SECONDS  = 10    # Señales más viejas que esto se ignoran
ORDER_CONFIRM_TIMEOUT  = 5     # Segundos para confirmar orden
ORDER_TIMEOUT          = int(os.getenv("ORDER_TIMEOUT", "10"))  # Timeout HTTP órdenes BingX
GIRO_BUFFER_SECONDS    = 0.3   # Espera entre cierre y apertura en giros
RECONCILE_INTERVAL     = 30    # Segundos entre reconciliaciones automáticas
# ============================================================
# 💰 SIZING — cálculo de qty en Python
# ============================================================
# RISK_PCT: fracción del balance disponible a usar como margen por entrada.
# BingX aplica el leverage configurado manualmente en el broker por símbolo.
# Ejemplo: balance=1000 USDT, RISK_PCT=0.05, leverage x10 en BingX
#   → Python usa 50 USDT de margen → posicion real de 500 USDT
#
# Configurable desde Render sin tocar codigo.
# Futuro: config por robot {"CAZADOR": 0.05, "HUNTER": 0.03}
RISK_PCT = float(os.getenv("RISK_PCT_DEFAULT", "0.05"))  # 5% por defecto
# ============================================================
# 📈 PIRÁMIDE — control máximo entradas por lado
# ============================================================
# Fallback si TV no manda pyramid_max en el JSON
PYRAMID_MAX_DEFAULT = int(os.getenv("PYRAMID_MAX_DEFAULT", "3"))

# ============================================================
# 🚨 VALIDACIONES AL ARRANQUE
# ============================================================
def validate():
    errors = []
    if not SIMULATION_MODE:
        if not BINGX_API_KEY or BINGX_API_KEY == "TEST_API_KEY_PLACEHOLDER":
            errors.append("BINGX_API_KEY no configurada")
        if not BINGX_API_SECRET or BINGX_API_SECRET == "TEST_API_SECRET_PLACEHOLDER":
            errors.append("BINGX_API_SECRET no configurada")
    if not WEBHOOK_SECRET_TOKEN:
        errors.append("WEBHOOK_SECRET_TOKEN no configurada")
    return errors
