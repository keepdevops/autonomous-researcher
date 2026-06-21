"""Shared HTTP fetch settings for web ingest."""
import os
from urllib.parse import urlparse

HTTP_USER_AGENT = os.getenv(
    "HTTP_USER_AGENT",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 AutonomousResearcher/2.0",
)


def default_headers() -> dict[str, str]:
    return {
        "User-Agent": HTTP_USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }


def parse_allowlist() -> set[str]:
    raw = os.getenv("RESEARCH_URL_ALLOWLIST", "").strip()
    if not raw:
        return set()
    return {d.strip().lower() for d in raw.split(",") if d.strip()}


def url_allowed(url: str, allowlist: set[str] | None = None) -> bool:
    if not url:
        return False
    allowlist = parse_allowlist() if allowlist is None else allowlist
    if not allowlist:
        return True
    host = urlparse(url).netloc.lower().split(":")[0]
    if host in allowlist:
        return True
    return any(host == d or host.endswith(f".{d}") for d in allowlist)
