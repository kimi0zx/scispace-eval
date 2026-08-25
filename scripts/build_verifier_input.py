"""Assemble the Claim Verifier's input pack: claims + section-scoped evidence."""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path("/Users/abishek/personal/scispace-eval")
DUMP = ROOT / "data/dump"
TID = "cea2bed8-15aa-409a-b3f3-fcf4285cd6c9"

bundle = json.loads((DUMP / TID / "bundle.json").read_text())
F = bundle["files"]

claims = json.loads(
    re.search(r"```json\s*(\[.*?\])\s*```", (DUMP / "claims_cea2bed8.md").read_text(), re.S).group(1)
)

SECTION_FILES = {
    "01_introduction": "Introduction",
    "02_imaging_approaches": "Imaging-Based AI Approaches",
    "03_genomics_approaches": "Genomics-Based AI Approaches",
    "04_multimodal_approaches": "Multimodal AI Approaches",
    "05_synthesis": "Comparative Analysis and Synthesis",
    "06_conclusion": "Conclusion",
}


def name_of(v) -> str | None:
    """Nested metadata comes back as either a string or a {display_name: ...} object."""
    if isinstance(v, dict):
        return v.get("display_name") or v.get("name")
    return v or None


def author_names(v) -> list[str]:
    items = v.get("data") if isinstance(v, dict) else v
    if not isinstance(items, list):
        return []
    return [n for n in (name_of(a) for a in items) if n]


def paper_of(row: dict) -> dict:
    return row[[k for k in row if k.startswith("papers_")][0]]


def cells_of(row: dict, columns: list[dict]) -> dict[str, str]:
    by_id = {c["column_id"]: c["name"] for c in columns}
    out = {}
    for cid, name in by_id.items():
        if cid.startswith(("papers_", "abstract_")):
            continue
        v = row.get(cid)
        if isinstance(v, dict):
            v = v.get("value") or v.get("text") or json.dumps(v, ensure_ascii=False)
        if isinstance(v, str) and v.strip():
            out[name] = v.strip()
    return out


# Build the evidence pool. Papers are keyed E1..En by DOI so the same paper keeps
# one id across sections, and the verifier can see when sections disagree about it.
pool: dict[str, dict] = {}
section_members: dict[str, list[str]] = {}

for stem, heading in SECTION_FILES.items():
    path = f"/home/sandbox/sections/{stem}_relevant.papertable"
    pt = json.loads(F[path]["text"])
    cols = pt["columns"]
    members = []
    for row in pt["data"]:
        p = paper_of(row)
        key = (p.get("doi") or p.get("unique_id") or p.get("title", ""))[:200].lower()
        rec = pool.setdefault(
            key,
            {
                "title": p.get("title"),
                "doi": p.get("doi"),
                "journal": name_of(p.get("journal")),
                "date": p.get("date"),
                "publication_type": p.get("publication_type"),
                "authors": author_names(p.get("authors"))[:6],
                "abstract": p.get("abstract"),
                "criteria_cells": {},
                "sections": [],
            },
        )
        rec["sections"].append(heading)
        for name, val in cells_of(row, cols).items():
            rec["criteria_cells"].setdefault(f"{heading} :: {name}", val)
        members.append(key)
    section_members[heading] = members

order = list(pool)
eid = {k: f"E{i}" for i, k in enumerate(order, 1)}

by_section: dict[str, list[dict]] = {}
for c in claims:
    by_section.setdefault(c["section"], []).append(c)

# Map each report section heading to the evidence set of the top-level section it
# sits under, since subsection headings do not have their own evidence tables.
SUB_TO_TOP = {
    "Introduction": "Introduction",
    "Imaging-Based AI Approaches": "Imaging-Based AI Approaches",
    "Performance Across Cancer Types": "Imaging-Based AI Approaches",
    "Model Architectures": "Imaging-Based AI Approaches",
    "Comparative Performance Patterns": "Imaging-Based AI Approaches",
    "Genomics-Based AI Approaches": "Genomics-Based AI Approaches",
    "Liquid Biopsy and Non-Invasive Detection": "Genomics-Based AI Approaches",
    "Performance of Genomics-Only Approaches": "Genomics-Based AI Approaches",
    "Machine Learning Approaches": "Genomics-Based AI Approaches",
    "Multimodal AI Approaches": "Multimodal AI Approaches",
    "Performance Gains Over Unimodal Approaches": "Multimodal AI Approaches",
    "Fusion Strategy Comparisons": "Multimodal AI Approaches",
    "Comparative Analysis and Synthesis": "Comparative Analysis and Synthesis",
    "Conclusion": "Conclusion",
}

out: list[str] = []
w = out.append

w("# Claim Verifier — Input Pack")
w("")
w(f"**Thread:** `{TID}` (`report_mode: verified`)  ")
w(f"**Claims to verify:** {len(claims)}  ")
w(f"**Evidence papers:** {len(pool)}  ")
w("**Source report:** `final_report.md` (21,325 chars)")
w("")
w("---")
w("")
w("## Your task")
w("")
w("For each claim below, decide whether the evidence in this pack supports it.")
w("You are verifying groundedness, not writing prose. One verdict record per claim.")
w("")
w("### Hard rules")
w("")
w("1. **Use only the evidence in this file.** Do not search the web, do not open other")
w("   files, do not rely on your own knowledge of the literature. If this pack does not")
w("   contain the evidence, the verdict is `insufficient_evidence` — that is a real and")
w("   expected answer, not a failure.")
w("2. **Quote or it did not happen.** Every verdict must carry `evidence_quote`: the exact")
w("   substring from an abstract or criteria cell you relied on. A verdict with no quote is")
w("   a guess. If you cannot quote, the verdict is `insufficient_evidence`.")
w("3. **Strict default.** Ambiguous or partial support is `unsupported`. Under-report")
w("   quality rather than over-report it.")
w("4. **Do not judge writing quality**, hedging, tone or completeness. Only: does the")
w("   evidence support this assertion.")
w("")
w("### The citation problem — read this carefully")
w("")
w("The report prints citation keys `[1]`–`[29]` but **ships no bibliography**, and the")
w("key-to-paper mapping is not recoverable from any available artefact. So you **cannot**")
w("check whether a claim cites the *right* paper.")
w("")
w("What this means for you:")
w("")
w("- Treat `cited_papers` as **uninterpretable metadata**. Do not try to guess which")
w("  paper `[7]` is, and never mark a claim unsupported because of its citation key.")
w("- Instead, search the **whole evidence set for that claim's section** and answer: does")
w("  *any* paper here support this assertion?")
w("- Set `citation_checkable: false` on every verdict. Citation-binding failures are")
w("  out of scope for this run and will be reported as a measurement limitation.")
w("")
w("### Verdict schema — one JSON object per claim")
w("")
w("```json")
w(json.dumps(
    {
        "id": "c17",
        "verdict": "supported | unsupported | insufficient_evidence",
        "supporting_evidence_ids": ["E12"],
        "evidence_quote": "exact substring from the abstract or criteria cell",
        "evidence_field": "abstract | criteria_cell",
        "severity": "fabricated | distorted | overreach | none",
        "citation_checkable": False,
        "reason": "one sentence naming the exact match or mismatch",
        "numeric_delta": "report value vs source value, or null",
    },
    indent=2,
))
w("```")
w("")
w("**`verdict`**")
w("")
w("- `supported` — a paper in the section's evidence set states this, and you can quote it.")
w("- `unsupported` — the evidence set addresses this topic but contradicts the claim, or")
w("  states a materially different value.")
w("- `insufficient_evidence` — nothing in the evidence set speaks to this claim. Common for")
w("  synthesis claims and for anything sourced from a paper's results tables rather than its")
w("  abstract. Not a hallucination.")
w("")
w("**`severity`** — only when `unsupported`:")
w("")
w("- `fabricated` — the value or finding appears nowhere in the evidence set.")
w("- `distorted` — right study and right metric, wrong value, or right value attached to the")
w("  wrong cohort, dataset or condition (e.g. validation reported as test).")
w("- `overreach` — the evidence points this way but is weaker than the claim states")
w("  (a single study generalised to 'most studies', a range presented as a ceiling).")
w("")
w("**For `type: synthesis` claims**, check the assertion against *every* relevant paper in")
w("the section set, not one. A superlative or aggregate is `unsupported` / `overreach` if the")
w("rows it summarises do not collectively bear it out. Say in `reason` how many papers you")
w("checked and how many actually supported it.")
w("")
w("### Output")
w("")
w("Write your results to")
w("`/Users/abishek/personal/scispace-eval/data/dump/verdicts_cea2bed8.md`, containing:")
w("")
w("1. A summary table: counts by verdict, by severity, by claim `type`, and by `materiality`.")
w("2. A per-section breakdown table.")
w("3. `## Full records` — the complete JSON array of all verdict objects in a ```json block.")
w("4. `## Notes` — claims you found hardest to judge and why, any evidence-set gaps you hit,")
w("   and any internal contradictions you noticed between papers.")
w("")
w("Do not skip claims. Every id must appear exactly once in the output.")
w("")
w("---")
w("")
w("## Evidence set")
w("")
w("Each paper has a stable `E` id. The same paper keeps its id across sections, so if two")
w("sections describe it differently, that is visible and worth flagging.")
w("")

for key in order:
    p = pool[key]
    w(f"### {eid[key]} — {p['title']}")
    w("")
    meta = [
        f"**DOI:** `{p['doi']}`" if p["doi"] else "**DOI:** none",
        f"**Journal:** {p['journal']}" if p["journal"] else None,
        f"**Date:** {p['date']}" if p["date"] else None,
        f"**Type:** {p['publication_type']}" if p["publication_type"] else None,
    ]
    w("  ·  ".join(m for m in meta if m))
    w("")
    if p["authors"]:
        w(f"**Authors:** {', '.join(a for a in p['authors'] if a)}")
        w("")
    w(f"**Appears in section evidence sets:** {', '.join(sorted(set(p['sections'])))}")
    w("")
    w("**Abstract**")
    w("")
    w("> " + (p["abstract"] or "_none_").replace("\n", "\n> "))
    w("")
    for name, val in p["criteria_cells"].items():
        w(f"**Criteria cell — {name}**")
        w("")
        w("> " + val.replace("\n", "\n> "))
        w("")

w("---")
w("")
w("## Section evidence sets")
w("")
w("Which papers are available as evidence for claims in each section.")
w("")
for heading, members in section_members.items():
    ids = [eid[m] for m in members]
    w(f"- **{heading}** ({len(ids)}): {', '.join(ids)}")
w("")
w("---")
w("")
w("## Claims to verify")
w("")

for section in [s for s in SUB_TO_TOP if s in by_section]:
    top = SUB_TO_TOP[section]
    ids = [eid[m] for m in section_members[top]]
    cs = by_section[section]
    w(f"### {section}")
    w("")
    w(f"_Evidence set ({top}): {', '.join(ids)}_")
    w("")
    for c in cs:
        w(f"**{c['id']}** · `{c['type']}` · `{c['materiality']}` · cited: {c['cited_papers'] or 'none'}")
        w("")
        w(f"- **Claim:** {c['claim']}")
        w(f"- **Verbatim:** \"{c['verbatim']}\"")
        w("")

text = "\n".join(out)
dest = DUMP / "verifier_input_cea2bed8.md"
dest.write_text(text)
print(f"{dest}  {len(text):,} chars  ~{len(text)//4:,} tokens")
print(f"papers {len(pool)}  claims {len(claims)}  sections {len(by_section)}")
