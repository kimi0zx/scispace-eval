"""External ground truth for cited papers.

Two rules this module exists to enforce:

1. Evidence comes from outside the pipeline under test. If stage 4 mis-extracts
   a value from an abstract and we re-read that abstract through SciSpace's own
   retrieval layer, the eval inherits the bug it is looking for.
2. A citation is invalid only if *both* registries fail it. Crossref alone
   flagged 3 of 29 references on the pilot run, of which 2 are genuine -
   publishers register DOIs with different agencies. Single-registry validation
   over-reports fabrication.

Existence checks (Crossref, OpenAlex) and abstract fetching (Semantic Scholar)
are separate passes on purpose. S2 is rate-limited to roughly 1 req/s without a
key; coupling it to the existence check makes the whole batch run at S2 speed.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from .. import config
from ..http import Client
from ..schema import SourceRecord

log = logging.getLogger(__name__)

DOI_RE = re.compile(r"^10\.\d{4,9}/\S+$")

# Registered as records but not peer-reviewed literature. A material distinction
# for a research audience, and one the report does not surface.
NON_PEER_REVIEWED_TYPES = {"posted-content", "dataset", "report", "preprint", "other"}
NON_PEER_REVIEWED_HOSTS = {"zenodo", "arxiv", "biorxiv", "medrxiv", "ssrn", "researchgate"}


def normalize_doi(raw: str | None) -> str | None:
    if not raw:
        return None
    d = raw.strip().lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:", "doi.org/"):
        if d.startswith(prefix):
            d = d[len(prefix) :]
    d = d.rstrip(".,;)")
    return d or None


def is_wellformed(doi: str | None) -> bool:
    return bool(doi and DOI_RE.match(doi))


def _crossref(c: Client, doi: str) -> dict | None:
    params = {}
    if email := config.contact_email():
        params["mailto"] = email
    data = c.get_json(
        f"https://api.crossref.org/works/{doi}",
        params=params or None,
        cache_key=f"crossref_{doi}",
        allow_404=True,
    )
    return (data or {}).get("message") if data else None


def _openalex(c: Client, doi: str) -> dict | None:
    params = {}
    if email := config.contact_email():
        params["mailto"] = email
    return c.get_json(
        f"https://api.openalex.org/works/doi:{doi}",
        params=params or None,
        cache_key=f"openalex_{doi}",
        allow_404=True,
    )


def _semantic_scholar(c: Client, doi: str) -> dict | None:
    return c.get_json(
        f"https://api.semanticscholar.org/graph/v1/paper/DOI:{doi}",
        params={"fields": "title,year,abstract,venue,publicationTypes,externalIds"},
        cache_key=f"s2_{doi}",
        allow_404=True,
    )


def _peer_reviewed(cr: dict | None, oa: dict | None) -> bool | None:
    blobs: list[str] = []
    if cr:
        blobs.append(str(cr.get("type", "")))
        blobs.extend(cr.get("container-title") or [])
    if oa:
        blobs.append(str(oa.get("type", "")))
        loc = (oa.get("primary_location") or {}).get("source") or {}
        blobs.append(str(loc.get("display_name", "")))
    if not blobs:
        return None
    joined = " ".join(blobs).lower()
    if any(t in joined for t in NON_PEER_REVIEWED_TYPES):
        return False
    if any(h in joined for h in NON_PEER_REVIEWED_HOSTS):
        return False
    return True


def resolve(doi_raw: str | None, existence: Client, abstracts: Client | None = None) -> SourceRecord:
    doi = normalize_doi(doi_raw)
    if not is_wellformed(doi):
        return SourceRecord(doi=doi or (doi_raw or ""), status="malformed")

    cr = _crossref(existence, doi)
    oa = _openalex(existence, doi)
    resolved_by = [n for n, v in (("crossref", cr), ("openalex", oa)) if v]

    rec = SourceRecord(
        doi=doi,
        resolved_by=resolved_by,
        status="resolved" if resolved_by else "unresolved",
        is_peer_reviewed=_peer_reviewed(cr, oa),
    )
    if cr:
        titles = cr.get("title") or []
        rec.title = titles[0] if titles else None
        rec.type = cr.get("type")
        containers = cr.get("container-title") or []
        rec.venue = containers[0] if containers else None
        parts = ((cr.get("issued") or {}).get("date-parts") or [[None]])[0]
        rec.year = parts[0] if parts else None
    if oa and not rec.title:
        rec.title = oa.get("title")
        rec.year = oa.get("publication_year")
        rec.type = oa.get("type")

    if abstracts is not None and rec.status == "resolved":
        s2 = _semantic_scholar(abstracts, doi)
        if s2 and s2.get("abstract"):
            rec.abstract = s2["abstract"]
            rec.abstract_source = "semantic_scholar"
        elif oa:
            inv = oa.get("abstract_inverted_index")
            if inv:
                rec.abstract = _from_inverted_index(inv)
                rec.abstract_source = "openalex"
    return rec


def _from_inverted_index(index: dict[str, list[int]]) -> str:
    positions: list[tuple[int, str]] = []
    for word, idxs in index.items():
        positions.extend((i, word) for i in idxs)
    positions.sort()
    return " ".join(w for _, w in positions)


def existence_client() -> Client:
    return Client(cache_dir=config.CACHE_DIR / "scholarly", min_interval=0.1)


def abstract_client() -> Client:
    key = config.s2_api_key()
    return Client(
        headers={"x-api-key": key} if key else None,
        cache_dir=config.CACHE_DIR / "scholarly",
        min_interval=0.2 if key else 1.2,
    )
