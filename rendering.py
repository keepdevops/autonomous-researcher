"""Headless-browser rendering for JavaScript-heavy pages.

Plain HTTP fetches return the server's initial HTML, which for client-rendered
(SPA) sites is mostly empty. This module drives a headless Chromium via
requests-html so the page's JavaScript runs before we extract text. Chromium is
downloaded automatically by requests-html/pyppeteer on first use.
"""

import logging

from requests_html import HTMLSession

logger = logging.getLogger(__name__)

# Seconds to wait for navigation and for the post-render settle pause.
RENDER_TIMEOUT = float(__import__("os").getenv("RENDER_TIMEOUT", "20"))
RENDER_SLEEP = float(__import__("os").getenv("RENDER_SLEEP", "1.0"))


def fetch_rendered_html(url: str, timeout: float = RENDER_TIMEOUT) -> str:
    """Load a URL in headless Chromium, run its JS, and return the final HTML.

    Fails loudly: any browser/network error is logged and re-raised as a
    RuntimeError so callers never silently fall back to empty content.
    """
    session = HTMLSession()
    try:
        resp = session.get(url, timeout=timeout)
        resp.raise_for_status()
        resp.html.render(timeout=timeout, sleep=RENDER_SLEEP)
        return resp.html.html or ""
    except Exception as exc:  # requests-html/pyppeteer raise a wide range
        logger.error("fetch_rendered_html failed for %r: %s", url, exc)
        raise RuntimeError(f"JS render failed: {exc}") from exc
    finally:
        session.close()
