from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]
# A real environment variable wins over .env, so CI and one-off shells can pass
# the cookie without touching the file.
load_dotenv(REPO_ROOT / ".env", override=False)

DATA_DIR = Path(os.getenv("SCISPACE_EVAL_DATA_DIR", REPO_ROOT / "data"))
RAW_DIR = DATA_DIR / "raw"          # thread listings and one-off fetches
PIPELINE_DIR = DATA_DIR / "pipeline"  # one directory per scored run

ORIGIN = "https://scispace.com"
# Two distinct API surfaces. The SciSpace wrapper owns thread listing and
# artefacts; the LangGraph runtime is reverse-proxied at /langgraph (not under
# /api/) and owns the run state that carries the message and tool-call history.
API_BASE = f"{ORIGIN}/api/scispace-agent"
LANGGRAPH_BASE = f"{ORIGIN}/langgraph"


class MissingCredentials(RuntimeError):
    pass


@dataclass(frozen=True)
class Credentials:
    cookie: str | None
    bearer: str | None

    def headers(self) -> dict[str, str]:
        if not self.cookie and not self.bearer:
            raise MissingCredentials(
                "No SciSpace credentials. Copy .env.example to .env and set "
                "SCISPACE_COOKIE from a logged-in browser session."
            )
        headers: dict[str, str] = {}
        if self.cookie:
            headers["cookie"] = self.cookie
        if self.bearer:
            headers["authorization"] = f"Bearer {self.bearer}"
        return headers


def credentials() -> Credentials:
    return Credentials(
        cookie=(os.getenv("SCISPACE_COOKIE") or "").strip() or None,
        bearer=(os.getenv("SCISPACE_AUTH_TOKEN") or "").strip() or None,
    )


def ensure_dirs() -> None:
    for d in (RAW_DIR, PIPELINE_DIR):
        d.mkdir(parents=True, exist_ok=True)
