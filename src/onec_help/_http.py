"""Shared HTTP/SSL helpers for fetchers (parse_helpf, parse_fastcode, standards_loader, parse_its_v8std)."""

from __future__ import annotations

import ssl
import urllib.error
import urllib.request

try:
    import certifi

    _SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    _SSL_CONTEXT = ssl.create_default_context()


def get_ssl_context() -> ssl.SSLContext:
    """Return default SSL context (certifi if available, else system)."""
    return _SSL_CONTEXT


def create_opener(ssl_context: ssl.SSLContext | None = None) -> urllib.request.OpenerDirector:
    """Build opener with HTTPSHandler. Uses module default context if context is None."""
    ctx = ssl_context if ssl_context is not None else _SSL_CONTEXT
    return urllib.request.build_opener(urllib.request.HTTPSHandler(context=ctx))


def create_opener_unverified() -> urllib.request.OpenerDirector:
    """Fallback when default SSL verification fails (e.g. Mac, missing CA bundle)."""
    ctx = ssl._create_unverified_context()  # noqa: S323
    return urllib.request.build_opener(urllib.request.HTTPSHandler(context=ctx))


def get_opener_for_base_url(
    base_url: str,
    path: str = "/",
    timeout: int = 10,
    user_agent: str = "Mozilla/5.0 (compatible; 1c-help-parser)",
) -> urllib.request.OpenerDirector:
    """Return opener; use unverified SSL if default fails (certificate verify issues)."""
    opener = create_opener()
    url = base_url.rstrip("/") + path
    try:
        req = urllib.request.Request(url, headers={"User-Agent": user_agent})
        opener.open(req, timeout=timeout)
        return opener
    except (urllib.error.URLError, OSError) as e:
        if "SSL" in str(e) or "certificate" in str(e).lower():
            return create_opener_unverified()
        raise


def fetch_url(
    url: str,
    opener: urllib.request.OpenerDirector,
    timeout: int = 30,
    user_agent: str = "Mozilla/5.0 (compatible; 1c-help-parser)",
) -> str:
    """Fetch URL with opener; return decoded UTF-8 body."""
    req = urllib.request.Request(url, headers={"User-Agent": user_agent})
    with opener.open(req, timeout=timeout) as r:
        return r.read().decode("utf-8")
