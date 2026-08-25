"""Recover the generated report and its evidence from a collected thread.

Two report-writing pipelines exist and they leave different traces:

  standard  `add_column_to_search_results_using_llm` builds criteria columns on one
            shared table; the report text lands in a `filesystem_file_write` arg.
  verified  each section is written by a sub-agent via
            `write_section_with_verification`, which builds its own criteria column
            and its own filtered table. The section text never enters the message
            list, so the report has to come from the artefact store.

Detecting the mode from the tool census rather than from thread metadata keeps this
working when the metadata is absent, which it often is on older threads.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

CITATION_RE = re.compile(r"\s*\[\s*\d+(\s*,\s*\d+)*\s*\]")
PLACEHOLDER_RE = re.compile(r"\s*\[[A-Za-z][^\]]{3,60}\]")


@dataclass
class SourcePaper:
    paper_id: str
    title: str | None = None
    doi: str | None = None
    journal: str | None = None
    date: str | None = None
    publication_type: str | None = None
    authors: list[str] = field(default_factory=list)
    abstract: str | None = None
    # Body text the full-text search matched, with the sections it came from.
    # Not the whole paper, but usually the passage carrying the figures a query
    # asked about, which the abstract often omits.
    passage: str | None = None
    passage_sections: list[str] = field(default_factory=list)
    is_oa: bool | None = None
    fulltext_url: str | None = None
    pmc_id: str | None = None
    # Criteria cells are LLM summaries produced by the extraction step. They are
    # kept because the report was written from them, which is what makes stage
    # attribution possible, but they are never treated as source text.
    criteria_cells: dict[str, str] = field(default_factory=dict)


@dataclass
class Extraction:
    thread_id: str
    mode: str
    report_markdown: str | None
    papers: list[SourcePaper]
    section_count: int = 0
    self_verification: list[dict] = field(default_factory=list)
    corrections: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(c.get("text", "") for c in content if isinstance(c, dict))
    return ""


def _name(v: Any) -> str | None:
    if isinstance(v, dict):
        return v.get("display_name") or v.get("name")
    return v or None


def _authors(v: Any) -> list[str]:
    items = v.get("data") if isinstance(v, dict) else v
    if not isinstance(items, list):
        return []
    return [n for n in (_name(a) for a in items) if n]


def _paper_of(row: dict) -> dict:
    keys = [k for k in row if k.startswith("papers_")]
    return row[keys[0]] if keys else {}


def _cells(row: dict, columns: list[dict]) -> dict[str, str]:
    out: dict[str, str] = {}
    for col in columns:
        cid, name = col.get("column_id", ""), col.get("name", "")
        # Papers/abstract are carried as first-class fields; Relevance is the
        # pipeline's own inclusion verdict and must not reach the verifier.
        if cid.startswith(("papers_", "abstract_")) or name.strip().lower() == "relevance":
            continue
        v = row.get(cid)
        if isinstance(v, dict):
            v = v.get("value") or v.get("text") or json.dumps(v, ensure_ascii=False)
        if isinstance(v, str) and v.strip():
            out[name] = v.strip()
    return out


def clean_report(text: str) -> str:
    """Strip citation markers.

    The reports ship no bibliography, so `[7]` resolves to nothing for a reader or
    a verifier. Left in, a marker makes a claim look attributed, which biases both
    the severity call and the reader's trust.
    """
    text = CITATION_RE.sub("", text)
    text = PLACEHOLDER_RE.sub("", text)
    text = re.sub(r" +([.,;:])", r"\1", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    return re.sub(r"[ \t]{2,}", " ", text)


def detect_mode(messages: list[dict]) -> str:
    tools = {c.get("name") for m in messages for c in (m.get("tool_calls") or [])}
    if "write_section_with_verification" in tools:
        return "verified"
    if "add_column_to_search_results_using_llm" in tools:
        return "standard"
    if "write_report" in tools:
        return "unknown_report_mode"
    return "not_a_report_run"


def _papertables(files: dict[str, dict]) -> list[tuple[str, dict]]:
    """Only the tables the report was written from.

    Retrieval writes one table per source query (arxiv, pubmed, scholar, ...) before
    consolidation. Those hold papers that never survived reranking and that the
    section writers never saw, so including them inflates the evidence set with
    material the report could not have drawn on. Keep the consolidated table and
    the per-section filtered tables; drop the rest.
    """
    tables = []
    for path, f in sorted(files.items()):
        if not path.endswith(".papertable") or f.get("status") != 200:
            continue
        stem = path.rsplit("/", 1)[-1]
        is_consolidated = "combined" in stem or "merged" in stem
        is_section = "/sections/" in path or stem.endswith("_relevant.papertable")
        if not (is_consolidated or is_section):
            continue
        try:
            tables.append((path, json.loads(f["text"])))
        except Exception:  # noqa: BLE001 - a malformed table is skipped, not fatal
            continue
    if not tables:
        # No consolidated table on this run; fall back to whatever exists rather
        # than returning an empty evidence set.
        for path, f in sorted(files.items()):
            if path.endswith(".papertable") and f.get("status") == 200:
                try:
                    tables.append((path, json.loads(f["text"])))
                except Exception:  # noqa: BLE001
                    continue
    return tables


def _label(path: str) -> str:
    stem = path.rsplit("/", 1)[-1].removesuffix(".papertable")
    return stem.removesuffix("_relevant")


def _passages(files: dict[str, dict]) -> dict[str, tuple[str, list[str]]]:
    """Body text keyed by DOI, harvested from the full-text search results.

    These tables are excluded from the evidence spine because they predate
    consolidation and hold papers the report never saw. The passages on them are
    still the only body text available anywhere in a run, so they are lifted out
    and attached to whichever papers did survive.
    """
    out: dict[str, tuple[str, list[str]]] = {}
    for path, f in sorted(files.items()):
        if not path.endswith(".papertable") or f.get("status") != 200:
            continue
        try:
            table = json.loads(f["text"])
        except Exception:  # noqa: BLE001
            continue
        for row in table.get("data") or []:
            p = _paper_of(row)
            text = p.get("text")
            key = (p.get("doi") or p.get("unique_id") or p.get("title") or "")[:200].lower()
            if not key or not isinstance(text, str) or not text.strip():
                continue
            # Keep the longest passage seen for a paper.
            if key not in out or len(text) > len(out[key][0]):
                out[key] = (text.strip(), [s for s in (p.get("section_names") or []) if s])
    return out


def collect_evidence(files: dict[str, dict]) -> list[SourcePaper]:
    """Union every paper table into one deduplicated evidence set.

    Deduplication is by DOI so a paper keeps one id across sections; where two
    sections describe it differently, both descriptions survive as separate cells
    and the disagreement stays visible.
    """
    tables = _papertables(files)
    passages = _passages(files)
    # Prefer the widest table as the spine, then layer section cells on top.
    tables.sort(key=lambda t: len(t[1].get("data") or []), reverse=True)

    pool: dict[str, SourcePaper] = {}
    order: list[str] = []
    for path, table in tables:
        columns = table.get("columns") or []
        section = _label(path)
        for row in table.get("data") or []:
            p = _paper_of(row)
            if not p:
                continue
            key = (p.get("doi") or p.get("unique_id") or p.get("title") or "")[:200].lower()
            if not key:
                continue
            if key not in pool:
                order.append(key)
                pool[key] = SourcePaper(
                    paper_id="",
                    title=p.get("title"),
                    doi=p.get("doi"),
                    journal=_name(p.get("journal")),
                    date=str(p.get("date")) if p.get("date") else None,
                    publication_type=p.get("publication_type"),
                    authors=_authors(p.get("authors"))[:6],
                    abstract=p.get("abstract"),
                    is_oa=p.get("is_oa"),
                    fulltext_url=p.get("fulltext_url"),
                    pmc_id=p.get("pmc_id"),
                )
            rec = pool[key]
            if not rec.abstract and p.get("abstract"):
                rec.abstract = p["abstract"]
            if not rec.passage and key in passages:
                rec.passage, rec.passage_sections = passages[key]
            for name, val in _cells(row, columns).items():
                rec.criteria_cells.setdefault(f"{section} :: {name}", val)

    papers = []
    for i, key in enumerate(order, 1):
        rec = pool[key]
        rec.paper_id = f"P{i}"
        papers.append(rec)
    return papers


# Files that live alongside the report but are not the report.
_NOT_THE_REPORT = ("report_plan", "report_summary", "plan.md", "summary.md", "criteria")


def _is_section_file(path: str) -> bool:
    stem = path.rsplit("/", 1)[-1]
    return "/sections/" in path or stem.startswith("section_") or stem.startswith("section-")


def _report_from_artifacts(files: dict[str, dict]) -> tuple[str | None, str | None]:
    """Find the generated report among the artefacts.

    Filenames are not stable across runs: a report may be `final_report.md` or be
    named after the query topic. So candidates are ranked rather than looked up,
    and the plan and summary files are excluded explicitly because both sit next to
    the report and the plan in particular is large enough to be mistaken for it.
    """
    md = {
        p: f["text"]
        for p, f in files.items()
        if p.endswith(".md") and f.get("status") == 200 and (f.get("text") or "").strip()
    }
    if not md:
        return None, None

    def usable(p: str) -> bool:
        stem = p.rsplit("/", 1)[-1].lower()
        return not any(bad in stem for bad in _NOT_THE_REPORT) and not _is_section_file(p)

    named = {p: t for p, t in md.items() if usable(p) and "report" in p.rsplit("/", 1)[-1].lower()}
    if named:
        best = max(named, key=lambda p: len(named[p]))
        return named[best], None

    sections = sorted(p for p in md if _is_section_file(p))
    if sections:
        return (
            "\n\n".join(md[p] for p in sections),
            f"report reassembled from {len(sections)} section files",
        )

    other = {p: t for p, t in md.items() if usable(p)}
    if other:
        best = max(other, key=lambda p: len(other[p]))
        return other[best], f"report taken from {best.rsplit('/', 1)[-1]} (no file named *report*)"
    return None, None


def extract(bundle: dict) -> Extraction:
    state = bundle.get("state") or {}
    messages = ((state.get("values") or {}).get("messages")) or []
    files = bundle.get("files") or {}
    mode = detect_mode(messages)
    notes: list[str] = []

    report: str | None = None
    if mode == "verified":
        # The assembled report is an artefact; section text is written to files the
        # message list never carries. Neither the report filename nor the section
        # layout is fixed -- runs name the report after their topic, and sections
        # appear either under a sections/ directory or as flat section_NN_* files.
        report, note = _report_from_artifacts(files)
        if note:
            notes.append(note)
    else:
        # Standard mode writes the report as a tool argument. Take the largest
        # write: earlier ones are the plan and intermediate drafts.
        best = ""
        for m in messages:
            for c in m.get("tool_calls") or []:
                if c.get("name") != "filesystem_file_write":
                    continue
                body = (c.get("args") or {}).get("content") or ""
                if isinstance(body, str) and len(body) > len(best):
                    best = body
        report = best or None
        if report is None:
            report, note = _report_from_artifacts(files)
            if note:
                notes.append(note)

    verifications = [
        json.loads(_text(m.get("content")))
        for m in messages
        if m.get("type") == "tool"
        and m.get("name") == "write_section_with_verification"
        and _text(m.get("content")).strip().startswith("{")
    ]
    corrections = [
        c.get("args") or {}
        for m in messages
        for c in (m.get("tool_calls") or [])
        if c.get("name") == "filesystem_replace_text_in_file"
    ]

    papers = collect_evidence(files)
    if not papers:
        notes.append("no paper tables fetched: evidence set is empty")
    if report and not report.strip():
        report = None

    return Extraction(
        thread_id=bundle.get("thread_id", "?"),
        mode=mode,
        report_markdown=clean_report(report) if report else None,
        papers=papers,
        section_count=len(verifications),
        self_verification=verifications,
        corrections=corrections,
        notes=notes,
    )
