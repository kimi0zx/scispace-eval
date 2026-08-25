"""Turn a raw LangGraph thread state into a canonical Run.

The pipeline is observable but not instrumentable, so stage boundaries are
recovered from the tool-call sequence. The mapping used here:

    stage 1  search_scholarly_literature / *_search      retrieval
    stage 2  rerank_and_combine_paper_tables             consolidation
    stage 3  add_column_to_search_results_using_llm      criteria + extraction prompt
    stage 4  read_paper_table (with columns)             the enriched table
    stage 5  filesystem_file_write                       the report

read_paper_table is called twice: once bare (metadata only) and once with
`columns` after enrichment. Only the latter carries cell data, so the parser
takes the last such call rather than the first.
"""

from __future__ import annotations

import json
import re
from typing import Any

from ..schema import (
    Completeness,
    Criterion,
    PaperRow,
    Retrieval,
    Run,
    ToolCall,
)

SEARCH_TOOLS = {
    "scispace_paper_search",
    "scispace_full_text_search",
    "google_scholar_search",
    "scispace_library_search",
    "arxiv_paper_search",
    "pubmed_basic_search",
}

# "## 12. Some Title - Chen et al. 2022 - 10.2196/27694"
_HEADING = re.compile(r"^##\s+(\d+)\.\s+(.*)$")
_FIELD = re.compile(r"^-\s+\*\*(.+?)\*\*:\s*(.*)$")
_COLUMN = re.compile(r"^####\s+(.+?)\s*$")
_YEAR = re.compile(r"\b(19|20)\d{2}\b")


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [c.get("text", "") for c in content if isinstance(c, dict)]
        return "\n".join(p for p in parts if p)
    return ""


def _split_heading(rest: str) -> tuple[str, str | None, int | None, str | None]:
    """Split 'Title - Authors Year - DOI' without breaking titles containing hyphens."""
    parts = [p.strip() for p in rest.split(" - ")]
    doi = None
    if len(parts) > 1 and parts[-1].startswith("10."):
        doi = parts.pop().strip()
    authors = parts.pop().strip() if len(parts) > 1 else None
    title = " - ".join(parts).strip()
    year = None
    if authors:
        m = _YEAR.search(authors)
        if m:
            year = int(m.group(0))
    return title, authors, year, doi


def parse_paper_table(markdown: str) -> tuple[list[PaperRow], list[str], int | None]:
    """Parse a read_paper_table result. Returns (rows, column names, total papers)."""
    columns: list[str] = []
    total: int | None = None
    rows: list[PaperRow] = []

    current: PaperRow | None = None
    current_col: str | None = None
    buf: list[str] = []
    in_available = False

    def flush_cell() -> None:
        nonlocal buf, current_col
        if current is not None and current_col:
            body = "\n".join(buf).strip()
            if body:
                current.cells[current_col] = body
        buf = []
        current_col = None

    for line in markdown.splitlines():
        stripped = line.strip()

        if stripped.startswith("## Available Columns"):
            in_available = True
            continue
        if in_available:
            if stripped.startswith("- "):
                columns.append(stripped[2:].strip())
                continue
            if stripped.startswith("#") or stripped.startswith("*"):
                in_available = False

        if total is None:
            m = _FIELD.match(stripped)
            if m and m.group(1) == "Total Papers":
                total = int(re.sub(r"\D", "", m.group(2)) or 0) or None

        m = _HEADING.match(stripped)
        if m:
            flush_cell()
            if current is not None:
                rows.append(current)
            title, authors, year, doi = _split_heading(m.group(2))
            current = PaperRow(
                position=int(m.group(1)),
                title=title,
                authors=authors,
                year=year,
                doi=doi,
            )
            continue

        m = _COLUMN.match(stripped)
        if m:
            flush_cell()
            current_col = m.group(1)
            continue

        if current is not None and current_col is None:
            m = _FIELD.match(stripped)
            if m and m.group(1) == "Journal":
                current.journal = m.group(2).strip() or None
            continue

        if current_col:
            if stripped == "---":
                flush_cell()
                continue
            buf.append(line)

    flush_cell()
    if current is not None:
        rows.append(current)

    # Column names as declared exclude generated ones only when the table lists
    # them; fall back to what actually appeared in the rows.
    if not columns:
        seen: list[str] = []
        for r in rows:
            for c in r.cells:
                if c not in seen:
                    seen.append(c)
        columns = seen
    return rows, columns, total


def normalize(thread_id: str, state: dict[str, Any]) -> Run:
    messages: list[dict[str, Any]] = (state.get("values") or {}).get("messages") or []
    meta = state.get("metadata") or {}

    run = Run(
        thread_id=thread_id,
        run_id=meta.get("run_id"),
        created_at=state.get("created_at"),
    )

    # Tool results are addressed by the call that produced them. LangGraph emits
    # them as separate messages, so index results by tool name in order.
    results_by_name: dict[str, list[str]] = {}
    for m in messages:
        if m.get("type") == "tool" and m.get("name"):
            results_by_name.setdefault(m["name"], []).append(_text(m.get("content")))

    criteria: list[Criterion] = []
    table_markdown: str | None = None
    report: str | None = None
    report_path: str | None = None
    queries: list[str] = []
    sources: list[str] = []

    step = 0
    for m in messages:
        if m.get("type") == "human" and run.user_query is None:
            run.user_query = _text(m.get("content")) or None
        for call in m.get("tool_calls") or []:
            step += 1
            name = call.get("name") or ""
            args = call.get("args") or {}
            run.tool_calls.append(
                ToolCall(step=step, agent=m.get("name"), tool=name, args=args)
            )

            if name in SEARCH_TOOLS:
                sources.append(name)
                q = args.get("query") or args.get("search_query")
                if isinstance(q, str):
                    queries.append(q)

            elif name == "add_column_to_search_results_using_llm":
                criteria.append(
                    Criterion(
                        name=args.get("column_name") or "?",
                        extraction_prompt=args.get("llm_prompt_template"),
                        used_full_text=args.get("use_full_text"),
                    )
                )

            elif name == "read_paper_table" and args.get("columns"):
                calls = results_by_name.get("read_paper_table") or []
                if calls:
                    table_markdown = calls[-1]
                run.retrieval.papers_read = args.get("page_size")

            elif name == "filesystem_file_write":
                content = args.get("content") or args.get("contents")
                if isinstance(content, str) and len(content) > (len(report or "")):
                    report = content
                    report_path = args.get("file_path") or args.get("path")

    run.criteria = criteria
    run.report_markdown = report
    run.report_path = report_path
    run.retrieval = Retrieval(
        sources_queried=sources,
        queries=queries,
        papers_read=run.retrieval.papers_read,
    )

    if table_markdown:
        rows, columns, total = parse_paper_table(table_markdown)
        run.papers = rows
        run.retrieval.total_papers = total
        for name in columns:
            if not any(c.name == name for c in criteria):
                run.criteria.append(Criterion(name=name, derived=False))

    run.completeness = assess(run)
    return run


def assess(run: Run) -> Completeness:
    c = Completeness(
        has_report=bool(run.report_markdown),
        has_table=bool(run.papers),
        has_criteria=any(c.derived for c in run.criteria),
        rows_with_doi=sum(1 for p in run.papers if p.doi),
    )
    if not c.has_report:
        c.reasons.append("no report artefact")
    if not c.has_table:
        c.reasons.append("no enriched paper table")
    if not any(cr.derived for cr in run.criteria):
        c.reasons.append("no agent-derived criteria columns")
    if c.has_table and c.rows_with_doi == 0:
        c.reasons.append("no resolvable paper identifiers")
    c.usable = not c.reasons
    return c
