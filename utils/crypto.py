"""
utils/crypto.py

Cifrado y descifrado AES-256-GCM para API keys en BD.
La clave maestra vive ÚNICAMENTE en la variable de entorno
MASTER_ENCRYPTION_KEY — nunca en código ni en GitHub.

Formato almacenado en BD:
    base64( nonce[12] + tag[16] + ciphertext )

Sesión 12 — módulo cifrado API keys
"""
import os
import base64
import secrets
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from logs.logger import get_logger

logger = get_logger(__name__)

# ============================================================
# 🔑 CLAVE MAESTRA
# ============================================================

def _get_master_key() -> bytes:
    """
    Lee MASTER_ENCRYPTION_KEY del entorno.
    Acepta hex (64 chars) o base64 (44 chars).
    Falla ruidosamente si no está configurada o es inválida.
    """
    raw = os.getenv("MASTER_ENCRYPTION_KEY", "").strip()
    if not raw:
        raise RuntimeError(
            "❌ MASTER_ENCRYPTION_KEY no configurada en Render. "
            "El sistema no puede arrancar sin clave maestra."
        )
    # Intentar hex primero (64 chars = 32 bytes)
    if len(raw) == 64:
        try:
            return bytes.fromhex(raw)
        except ValueError:
            pass
    # Intentar base64 (44 chars = 32 bytes)
    try:
        key = base64.b64decode(raw)
        if len(key) == 32:
            return key
    except Exception:
        pass

    raise RuntimeError(
        "❌ MASTER_ENCRYPTION_KEY inválida. "
        "Debe ser 32 bytes en hex (64 chars) o base64 (44 chars)."
    )


# ============================================================
# 🔒 CIFRADO / DESCIFRADO
# ============================================================

def encrypt(plaintext: str) -> str:
    """
    Cifra un string con AES-256-GCM.
    Devuelve string base64 listo para guardar en BD.
    Cada llamada genera un nonce aleatorio distinto.
    """
    key    = _get_master_key()
    nonce  = secrets.token_bytes(12)          # 96 bits — estándar GCM
    aesgcm = AESGCM(key)
    ct     = aesgcm.encrypt(nonce, plaintext.encode(), None)
    # ct ya incluye el tag GCM al final (últimos 16 bytes)
    blob   = nonce + ct                       # 12 + len(plaintext) + 16
    return base64.b64encode(blob).decode()


def decrypt(encoded: str) -> str:
    """
    Descifra un string cifrado con encrypt().
    Lanza excepción si la clave es incorrecta o el dato fue manipulado.
    """
    key    = _get_master_key()
    blob   = base64.b64decode(encoded)
    nonce  = blob[:12]
    ct     = blob[12:]                        # ciphertext + tag GCM
    aesgcm = AESGCM(key)
    return aesgcm.decrypt(nonce, ct, None).decode()


# ============================================================
# 🛠️ UTILIDADES
# ============================================================

def generate_master_key() -> str:
    """
    Genera una clave maestra nueva en formato hex.
    Usar UNA SOLA VEZ para obtener el valor a pegar en Render.
    Nunca llamar en producción — solo como herramienta de setup.
    """
    return secrets.token_hex(32)   # 32 bytes = 256 bits


def mask(value: str, visible: int = 6) -> str:
    """
    Enmascara un string sensible para logs.
    Ej: mask("ABCDEF123456") → "ABCDEF******"
    """
    if not value or len(value) <= visible:
        return "***"
    return value[:visible] + "*" * (len(value) - visible)
