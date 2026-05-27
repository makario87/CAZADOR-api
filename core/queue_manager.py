"""
core/queue_manager.py

Cola de señales por usuario — #12c multi-usuario.
Cada usuario tiene su propia cola y su propio worker thread.
Sin bloqueo cruzado entre usuarios.

Backward compatible: enqueue(payload) sin user_id → DEFAULT_USER.
"""
import threading
import queue
from data.state import DEFAULT_USER
from logs.logger import get_logger

logger = get_logger(__name__)

_queues  = {}   # { user_id: queue.Queue() }
_workers = {}   # { user_id: Thread }
_lock    = threading.Lock()


def _get_queue(user_id: str = DEFAULT_USER) -> queue.Queue:
    """Devuelve cola del usuario, creando entrada vacía si no existe."""
    if user_id not in _queues:
        _queues[user_id] = queue.Queue()
    return _queues[user_id]


def enqueue(payload: dict, user_id: str = DEFAULT_USER):
    """Añade señal a la cola del usuario."""
    with _lock:
        q = _get_queue(user_id)
    q.put(payload)
    logger.info(
        f"📥 Señal encolada [{user_id}]: "
        f"{payload.get('signal')} | "
        f"cola={q.qsize()}"
    )
    # Arrancar worker si no está vivo
    _ensure_worker(user_id)


def _ensure_worker(user_id: str = DEFAULT_USER):
    """Arranca worker para el usuario si no está corriendo."""
    with _lock:
        w = _workers.get(user_id)
        if w and w.is_alive():
            return
        w = threading.Thread(
            target=_process_loop,
            args=(user_id,),
            daemon=True
        )
        _workers[user_id] = w
        w.start()
        logger.info(f"🚀 Queue worker arrancado [{user_id}]")


def start_worker(user_id: str = DEFAULT_USER):
    """
    Arranca worker para un usuario específico.
    Llamado desde app.py al arranque — backward compatible.
    """
    _ensure_worker(user_id)


def _process_loop(user_id: str):
    """Loop infinito que procesa señales de la cola del usuario."""
    from core.signal_handler import handle_signal
    q = _get_queue(user_id)
    while True:
        try:
            payload = q.get(timeout=1)
            logger.info(
                f"⚙️ Procesando señal [{user_id}]: "
                f"{payload.get('signal')}"
            )
            handle_signal(payload)
            q.task_done()
        except queue.Empty:
            continue
        except Exception as e:
            logger.error(f"❌ Error en queue worker [{user_id}]: {e}")


def queue_size(user_id: str = DEFAULT_USER) -> int:
    """Tamaño de cola para un usuario. Sin user_id → DEFAULT_USER."""
    with _lock:
        return _get_queue(user_id).qsize()


def queue_size_all() -> dict:
    """Tamaño de cola para todos los usuarios activos. Útil para /health."""
    with _lock:
        return {uid: q.qsize() for uid, q in _queues.items()}
