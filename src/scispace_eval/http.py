from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

import requests
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

log = logging.getLogger(__name__)

BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


class AuthExpired(RuntimeError):
    """The session cookie is no longer valid; re-copy it from the browser."""


class Transient(RuntimeError):
    """Retryable: 429 or 5xx."""


class Client:
    """Thin HTTP wrapper: browser-shaped headers, backoff on transients, optional disk cache.

    Cached responses are keyed by the caller-supplied cache key, not the URL, so
    paginated or POST-shaped calls can still be cached deterministically.
    """

    def __init__(
        self,
        headers: dict[str, str] | None = None,
        cache_dir: Path | None = None,
        min_interval: float = 0.0,
    ) -> None:
        self.session = requests.Session()
        self.session.headers.update({"accept": "application/json", "user-agent": BROWSER_UA})
        if headers:
            self.session.headers.update(headers)
        self.cache_dir = cache_dir
        if cache_dir:
            cache_dir.mkdir(parents=True, exist_ok=True)
        self.min_interval = min_interval
        self._last_call = 0.0

    def _throttle(self) -> None:
        if self.min_interval <= 0:
            return
        gap = time.monotonic() - self._last_call
        if gap < self.min_interval:
            time.sleep(self.min_interval - gap)
        self._last_call = time.monotonic()

    def _cache_path(self, key: str) -> Path | None:
        if not self.cache_dir:
            return None
        safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in key)[:180]
        return self.cache_dir / f"{safe}.json"

    @retry(
        retry=retry_if_exception_type(
            (Transient, requests.ConnectionError, requests.Timeout)
        ),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        stop=stop_after_attempt(5),
        reraise=True,
    )
    def _request(self, method: str, url: str, **kw: Any) -> requests.Response:
        self._throttle()
        resp = self.session.request(method, url, timeout=kw.pop("timeout", 60), **kw)
        if resp.status_code in (401, 403):
            raise AuthExpired(f"{resp.status_code} on {url}: {resp.text[:200]}")
        if resp.status_code == 429 or resp.status_code >= 500:
            raise Transient(f"{resp.status_code} on {url}")
        resp.raise_for_status()
        return resp

    def get_json(
        self,
        url: str,
        params: dict[str, Any] | None = None,
        cache_key: str | None = None,
        allow_404: bool = False,
    ) -> Any:
        path = self._cache_path(cache_key) if cache_key else None
        if path and path.exists():
            return json.loads(path.read_text())
        try:
            resp = self._request("GET", url, params=params)
        except requests.HTTPError as exc:
            if allow_404 and exc.response is not None and exc.response.status_code == 404:
                return None
            raise
        data = resp.json()
        if path:
            path.write_text(json.dumps(data, indent=2))
        return data

    def get_raw(self, url: str, params: dict[str, Any] | None = None) -> str:
        return self._request("GET", url, params=params).text
