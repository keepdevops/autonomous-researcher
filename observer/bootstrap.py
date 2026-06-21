"""Install default subscribers once per process."""
import sys
from pathlib import Path

from observer import hub
from observer.subscribers import log_subscriber, store_subscriber


def ensure_repo_root_on_path() -> Path:
    root = Path(__file__).resolve().parents[1]
    root_s = str(root)
    if root_s not in sys.path:
        sys.path.insert(0, root_s)
    return root


def install(*, enable_log: bool = True, enable_store: bool = True) -> None:
    ensure_repo_root_on_path()
    if hub.is_installed():
        return
    if enable_log:
        hub.subscribe(log_subscriber)
    if enable_store:
        hub.subscribe(store_subscriber)
    hub.mark_installed()
