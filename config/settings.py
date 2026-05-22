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
# 🔐 SEGURIDAD WEBHOOK
# ============================================================
WEBHOOK_SECRET_TOKEN = os.getenv("WEBHOOK_SECRET_TOKEN", "")

# ============================================================
# ⚙️ MODO OPERATIVO
# ============================================================
DEMO_MODE = os.getenv("DEMO_MODE", "true").lower() == "true"

# ============================================================
# 🌐 ENDPOINTS BINGX
# ============================================================
BINGX_BASE_URL = "https://open-api.bingx.com"

# ============================================================
# ⏱️ CONFIGURACIÓN SISTEMA
# ============================================================
SIGNAL_EXPIRY_SECONDS  = 10    # Señales más viejas que esto se ignoran
ORDER_CONFIRM_TIMEOUT  = 5     # Segundos para confirmar orden
GIRO_BUFFER_SECONDS    = 0.3   # Espera entre cierre y apertura en giros
RECONCILE_INTERVAL     = 30    # Segundos entre reconciliaciones automáticas

# ============================================================
# 🚨 VALIDACIONES AL ARRANQUE
# ============================================================
def validate():
    errors = []
    if not BINGX_API_KEY or BINGX_API_KEY == "TEST_API_KEY_PLACEHOLDER":
        errors.append("BINGX_API_KEY no configurada")
    if not BINGX_API_SECRET or BINGX_API_SECRET == "TEST_API_SECRET_PLACEHOLDER":
        errors.append("BINGX_API_SECRET no configurada")
    if not WEBHOOK_SECRET_TOKEN:
        errors.append("WEBHOOK_SECRET_TOKEN no configurada")
    return errors
