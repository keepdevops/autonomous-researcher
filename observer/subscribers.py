"""Built-in observer subscribers."""
import json
import logging

from observer.events import SystemEvent
from observer import store

logger = logging.getLogger(__name__)


def log_subscriber(event: SystemEvent) -> None:
    meta = json.dumps(event.metadata, ensure_ascii=False)[:200] if event.metadata else ""
    suffix = f" {meta}" if meta else ""
    logger.info(
        "observer %s/%s %s %s status=%s detail=%s%s",
        event.component.value,
        event.kind.value,
        event.run_id or "-",
        event.step or "-",
        event.status,
        event.detail[:120],
        suffix,
    )


def store_subscriber(event: SystemEvent) -> None:
    store.persist(event)
