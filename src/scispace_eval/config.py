from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(REPO_ROOT / ".env")

DATA_DIR = Path(os.getenv("SCISPACE_EVAL_DATA_DIR", REPO_ROOT / "data"))
RAW_DIR = DATA_DIR / "raw"
RUNS_DIR = DATA_DIR / "runs"
CACHE_DIR = DATA_DIR / "cache"
LABELS_DIR = DATA_DIR / "labels"
OUT_DIR = DATA_DIR / "out"

API_BASE = "https://scispace.com/api/scispace-agent"


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


def contact_email() -> str | None:
    return (os.getenv("SCHOLARLY_CONTACT_EMAIL") or "").strip() or None


def s2_api_key() -> str | None:
    return (os.getenv("SEMANTIC_SCHOLAR_API_KEY") or "").strip() or None


def ensure_dirs() -> None:
    for d in (RAW_DIR, RUNS_DIR, CACHE_DIR, LABELS_DIR, OUT_DIR):
        d.mkdir(parents=True, exist_ok=True)
