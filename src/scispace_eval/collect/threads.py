"""Enumerate runs and pull each run's raw artefacts.

The API is undocumented, so endpoint paths are treated as configuration with a
probe command to confirm them rather than being hardcoded on faith. Raw
responses are always written to disk before parsing: the parser will change as
the eval grows, and re-collecting is expensive and rate-limited.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Iterator

from .. import config
from ..http import AuthExpired, Client

log = logging.getLogger(__name__)

THREADS_PATH = "/threads"

# Confirmed against the live API. The LangGraph base is discoverable from the
# web bundle (NEXT_PUBLIC_LANGGRAPH_API_URL, defaulting to `${origin}/langgraph`)
# and is a separate surface from /api/scispace-agent, which 404s on /state.
STATE_URLS = (
    config.LANGGRAPH_BASE + "/threads/{tid}/state",
    config.LANGGRAPH_BASE + "/threads/{tid}",
)
ARTIFACT_URLS = (config.API_BASE + "/threads/{tid}/artifacts",)


def client() -> Client:
    return Client(
        headers=config.credentials().headers(),
        cache_dir=None,
        min_interval=0.4,
    )


def list_threads(
    c: Client, page_size: int = 20, max_pages: int = 50, is_pinned: bool = False
) -> Iterator[dict[str, Any]]:
    """Page through the thread list. Stops on the first empty or short page."""
    for page in range(max_pages):
        data = c.get_json(
            config.API_BASE + THREADS_PATH,
            params={"page_size": page_size, "page": page, "is_pinned": str(is_pinned).lower()},
        )
        items = _items(data)
        if not items:
            return
        for item in items:
            yield item
        if len(items) < page_size:
            return


def _items(data: Any) -> list[dict[str, Any]]:
    """Tolerate the common envelope shapes rather than assuming one."""
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("data", "threads", "items", "results"):
            v = data.get(key)
            if isinstance(v, list):
                return v
    return []


def thread_id_of(item: dict[str, Any]) -> str | None:
    for key in ("thread_id", "id", "threadId", "uuid"):
        v = item.get(key)
        if isinstance(v, str) and v:
            return v
    return None


def _first_working(c: Client, urls: tuple[str, ...], tid: str) -> tuple[str, Any] | None:
    for tmpl in urls:
        url = tmpl.format(tid=tid)
        try:
            data = c.get_json(url, allow_404=True)
        except AuthExpired:
            raise
        except Exception as exc:  # noqa: BLE001 - probing; a bad path is not fatal
            log.debug("probe failed %s: %s", url, exc)
            continue
        if data:
            return tmpl, data
    return None


def fetch_raw(c: Client, tid: str, raw_dir: Path | None = None, force: bool = False) -> dict[str, Any]:
    """Fetch and persist one thread's state and artifact list."""
    raw_dir = raw_dir or config.RAW_DIR
    raw_dir.mkdir(parents=True, exist_ok=True)
    out = raw_dir / f"{tid}.json"
    if out.exists() and not force:
        return json.loads(out.read_text())

    bundle: dict[str, Any] = {"thread_id": tid}
    got = _first_working(c, STATE_URLS, tid)
    if got:
        bundle["state_path"], bundle["state"] = got
    got = _first_working(c, ARTIFACT_URLS, tid)
    if got:
        bundle["artifacts_path"], bundle["artifacts"] = got

    out.write_text(json.dumps(bundle, indent=2))
    return bundle


def probe(c: Client, tid: str) -> dict[str, str | None]:
    """Report which candidate endpoint paths actually work, for one known thread."""
    state = _first_working(c, STATE_URLS, tid)
    arts = _first_working(c, ARTIFACT_URLS, tid)
    return {
        "threads": THREADS_PATH,
        "state": state[0] if state else None,
        "artifacts": arts[0] if arts else None,
    }
