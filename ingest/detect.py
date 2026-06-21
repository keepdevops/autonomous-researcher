from pathlib import Path

from ingest.models import DocType

_SUFFIX: dict[str, DocType] = {
    ".md": "markdown",
    ".markdown": "markdown",
    ".pdf": "pdf",
    ".py": "code",
    ".js": "code",
    ".ts": "code",
    ".go": "code",
    ".rs": "code",
    ".java": "code",
    ".cpp": "code",
    ".c": "code",
    ".html": "web",
    ".htm": "web",
}


def from_path(path: str | Path) -> DocType:
    suffix = Path(path).suffix.lower()
    return _SUFFIX.get(suffix, "text")


def from_url(url: str) -> DocType:
    lower = url.lower().split("?")[0]
    for suffix, dtype in _SUFFIX.items():
        if lower.endswith(suffix):
            return dtype
    return "web"
