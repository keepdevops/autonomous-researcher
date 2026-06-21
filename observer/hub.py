"""Thread-safe publish/subscribe hub — single bus for all components."""
import logging
import threading
import time
from collections.abc import Callable

from observer.events import SystemEvent

logger = logging.getLogger(__name__)

Subscriber = Callable[[SystemEvent], None]

_lock = threading.Lock()
_subscribers: list[Subscriber] = []
_installed = False


def subscribe(fn: Subscriber) -> None:
    with _lock:
        if fn not in _subscribers:
            _subscribers.append(fn)


def unsubscribe(fn: Subscriber) -> None:
    with _lock:
        if fn in _subscribers:
            _subscribers.remove(fn)


def publish(event: SystemEvent) -> None:
    if event.ts is None:
        event.ts = time.time()
    with _lock:
        targets = list(_subscribers)
    for fn in targets:
        try:
            fn(event)
        except Exception as exc:
            logger.error("observer subscriber %s failed: %s", fn, exc)


def subscriber_count() -> int:
    with _lock:
        return len(_subscribers)


def mark_installed() -> None:
    global _installed
    _installed = True


def is_installed() -> bool:
    return _installed
