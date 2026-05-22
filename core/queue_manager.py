"""
core/queue_manager.py
Cola de señales para procesar en orden sin perder ninguna.
Evita race conditions cuando llegan señales simultáneas.
TODO: persistir cola en Redis para sobrevivir reinicios de Render.
"""
import threading
import queue
from logs.logger import get_logger

logger = get_logger(__name__)

_queue  = queue.Queue()
_worker = None

def enqueue(payload: dict):
    """Añade una señal a la cola."""
    _queue.put(payload)
    logger.info(f"📥 Señal encolada: {payload.get('signal')} | cola={_queue.qsize()}")

def start_worker():
    """Arranca el worker en background que procesa la cola."""
    global _worker
    if _worker and _worker.is_alive():
        return
    _worker = threading.Thread(target=_process_loop, daemon=True)
    _worker.start()
    logger.info("🚀 Queue worker arrancado")

def _process_loop():
    """Loop infinito que procesa señales de la cola."""
    from core.signal_handler import handle_signal
    while True:
        try:
            payload = _queue.get(timeout=1)
            logger.info(f"⚙️ Procesando señal: {payload.get('signal')}")
            handle_signal(payload)
            _queue.task_done()
        except queue.Empty:
            continue
        except Exception as e:
            logger.error(f"❌ Error en queue worker: {e}")

def queue_size() -> int:
    return _queue.qsize()
