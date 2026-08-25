"""Render prompt inputs from a collected thread."""

from __future__ import annotations

import json
from pathlib import Path

from .report import Extraction, SourcePaper

PROMPTS = Path(__file__).parent / "prompts"


def _blockquote(text: str) -> str:
    return "> " + text.replace("\n", "\n> ")


def render_evidence(papers: list[SourcePaper]) -> str:
    out: list[str] = []
    w = out.append
    w(f"{len(papers)} sources. Ids `P1`–`P{len(papers)}`.")
    w("")
    w("Sources with no abstract carry metadata only and are unusable as evidence.")
    w("")
    for p in papers:
        w(f"## {p.paper_id} — {p.title or '(no title)'}")
        w("")
        meta = [f"**DOI:** `{p.doi}`" if p.doi else "**DOI:** none"]
        if p.journal:
            meta.append(f"**Journal:** {p.journal}")
        if p.date:
            meta.append(f"**Date:** {p.date}")
        if p.publication_type:
            meta.append(f"**Type:** {p.publication_type}")
        w("  ·  ".join(meta))
        w("")
        if p.authors:
            w(f"**Authors:** {', '.join(p.authors)}")
            w("")
        w("**Abstract**")
        w("")
        w(_blockquote(p.abstract) if p.abstract else "> _no abstract available_")
        w("")
        for name, val in p.criteria_cells.items():
            w(f"**Extracted data cell — {name}**")
            w("")
            w(_blockquote(val))
            w("")
    return "\n".join(out)


def render_claims(claims: list[dict]) -> str:
    out: list[str] = []
    w = out.append
    w(f"{len(claims)} claims to verify.")
    w("")
    by_section: dict[str, list[dict]] = {}
    for c in claims:
        by_section.setdefault(c.get("section") or "(no section)", []).append(c)
    for section, cs in by_section.items():
        w(f"## {section}")
        w("")
        for c in cs:
            w(f"**{c['id']}** · `{c.get('type')}` · `{c.get('severity')}`")
            w("")
            w(f"- **Claim:** {c.get('claim')}")
            w(f"- **Verbatim:** \"{c.get('verbatim')}\"")
            w("")
    return "\n".join(out)


def extractor_prompt(ex: Extraction, out_file: Path, dest: Path) -> Path:
    if not ex.report_markdown:
        raise ValueError(f"{ex.thread_id}: no report recovered (mode={ex.mode})")
    tmpl = (PROMPTS / "extractor.md").read_text()
    body = tmpl.replace("{report}", ex.report_markdown)
    body += f"\n\n---\n\nWrite your output to `{dest}`.\n"
    out_file.write_text(body)
    return out_file


def verifier_prompt(claims: list[dict], papers: list[SourcePaper], out_file: Path, dest: Path) -> Path:
    tmpl = (PROMPTS / "verifier.md").read_text()
    body = tmpl.replace("{claims}", render_claims(claims)).replace(
        "{evidence}", render_evidence(papers)
    )
    body += f"\n\n---\n\nWrite your output to `{dest}`.\n"
    out_file.write_text(body)
    return out_file


def parse_json_block(path: Path) -> list[dict]:
    """Pull the fenced JSON array out of an agent's markdown output."""
    import re

    text = path.read_text()
    blocks = re.findall(r"```json\s*(\[.*?\])\s*```", text, re.S)
    if not blocks:
        raise ValueError(f"{path}: no fenced json array found")
    # The records array is the largest block; summary snippets are smaller.
    best = max(blocks, key=len)
    return json.loads(best)
