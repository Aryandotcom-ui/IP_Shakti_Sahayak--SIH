"""
ai/updates/fetch.py

The one piece of the auto-update pipeline that talks to the outside
world. Kept to a single narrow `Fetcher` protocol — `fetch(url) -> bytes`
— so the watcher and every test against it can swap in a fake without
touching a network.

Stdlib only (`urllib`), deliberately. This runs on a schedule against a
handful of government sites; it does not need a connection-pooling HTTP
client, and not adding one keeps `ai/updates` installable with nothing
beyond what `ai/requirements.txt` already pulls in.
"""

from __future__ import annotations

import logging
import urllib.error
import urllib.request
from typing import Protocol

log = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 20  # seconds
USER_AGENT = "ip-sakti-sahayak-source-watcher/1.0 (+regulatory update check)"


class FetchError(Exception):
    """A source could not be fetched. Never lets a watch cycle crash —
    watcher.py catches this per-source and moves on to the next one."""


class Fetcher(Protocol):
    def fetch(self, url: str) -> bytes: ...


class HttpFetcher:
    """Fetches over HTTP(S). A 404/timeout/connection error becomes a
    FetchError rather than propagating — one unreachable source (a site
    under maintenance, a changed URL) must not stop the rest of the batch
    from being checked, the same principle ai/pipeline.py applies to a
    single bad PDF."""

    def __init__(self, timeout: int = DEFAULT_TIMEOUT) -> None:
        self.timeout = timeout

    def fetch(self, url: str) -> bytes:
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return response.read()
        except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
            raise FetchError(f"{url}: {exc}") from exc


class StaticFetcher:
    """Test/offline double: returns pre-registered bytes for a URL and
    raises FetchError for anything else. Also useful for a demo run
    against fixture content with no network access."""

    def __init__(self, content: dict[str, bytes] | None = None) -> None:
        self._content = dict(content or {})

    def set(self, url: str, content: bytes) -> None:
        self._content[url] = content

    def fetch(self, url: str) -> bytes:
        if url not in self._content:
            raise FetchError(f"{url}: no fixture content registered")
        return self._content[url]
