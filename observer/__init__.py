"""Central observer bus connecting orchestrator, researcher, memory, and tools."""
from observer.bootstrap import ensure_repo_root_on_path, install
from observer.events import Component, EventKind, SystemEvent
from observer.hub import is_installed, publish, subscribe, unsubscribe
from observer import store

def ensure() -> None:
    """Install default subscribers once per process."""
    from observer.bootstrap import install
    from observer.hub import is_installed

    if not is_installed():
        install()


ensure_repo_root_on_path()

__all__ = [
    "Component",
    "EventKind",
    "SystemEvent",
    "publish",
    "subscribe",
    "unsubscribe",
    "install",
    "ensure",
    "is_installed",
    "store",
    "ensure_repo_root_on_path",
]
