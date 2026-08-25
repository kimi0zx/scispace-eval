"""Full-scope evidence pack for adjudicating individual verdicts.

The verifier ran with section-scoped evidence (20 papers). That scoping is a
plausible source of false failures, so adjudication widens to the entire filtered
paper table the section writer actually had access to (351 papers), plus the
richer per-section criteria cells for the 55 papers that appear in any section set.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path("/Users/abishek/personal/scispace-eval")
DUMP = ROOT / "data/dump"
TID = "cea2bed8-15aa-409a-b3f3-fcf4285cd6c9"
F = json.loads((DUMP / TID / "bundle.json").read_text())["files"]

SECTIONS = {
    "01_introduction": "Introduction",
    "02_imaging_approaches": "Imaging-Based AI Approaches",
    "03_genomics_approaches": "Genomics-Based AI Approaches",
    "04_multimodal_approaches": "Multimodal AI Approaches",
    "05_synthesis": "Comparative Analysis and Synthesis",
    "06_conclusion": "Conclusion",
}


def paper_of(row): return row[[k for k in row if k.startswith("papers_")][0]]
def name_of(v): return (v.get("display_name") or v.get("name")) if isinstance(v, dict) else v


def authors(v):
    items = v.get("data") if isinstance(v, dict) else v
    return [n for n in (name_of(a) for a in (items or [])) if n] if isinstance(items, list) else []


def cells(row, columns):
    out = {}
    for c in columns:
        cid, nm = c["column_id"], c["name"]
        if cid.startswith(("papers_", "abstract_")):
            continue
        v = row.get(cid)
        if isinstance(v, dict):
            v = v.get("value") or v.get("text") or json.dumps(v, ensure_ascii=False)
        if isinstance(v, str) and v.strip():
            out[nm] = v.strip()
    return out


# Section criteria cells, keyed by DOI, so the E-ids in the verifier's reasoning
# stay traceable during adjudication.
extra: dict[str, dict] = {}
eid_by_doi: dict[str, str] = {}
order: list[str] = []
for stem, heading in SECTIONS.items():
    pt = json.loads(F[f"/home/sandbox/sections/{stem}_relevant.papertable"]["text"])
    for row in pt["data"]:
        p = paper_of(row)
        key = (p.get("doi") or p.get("unique_id") or p.get("title", ""))[:200].lower()
        if key not in eid_by_doi:
            order.append(key)
            eid_by_doi[key] = ""
        rec = extra.setdefault(key, {"sections": [], "cells": {}})
        rec["sections"].append(heading)
        for nm, val in cells(row, pt["columns"]).items():
            rec["cells"].setdefault(f"{heading} :: {nm}", val)
for i, k in enumerate(order, 1):
    eid_by_doi[k] = f"E{i}"

ft = json.loads(F["/home/sandbox/combined_ai_cancer_detection_filtered.papertable"]["text"])
rows = [paper_of(r) for r in ft["data"]]
ftcells = [cells(r, ft["columns"]) for r in ft["data"]]

out: list[str] = []
w = out.append
w("# Adjudication Evidence Pack — full scope")
w("")
w("Every paper in the filtered paper table the report's section writers had access to:")
w(f"**{len(rows)} papers**, ids `P1`–`P{len(rows)}`.")
w("")
w("Where a paper also appeared in a section's relevant set, its stable `E` id from the")
w("original verifier run is shown, along with that section's criteria cells. The `E` ids")
w("let you trace the original verdict's reasoning; the `P` ids cover everything else.")
w("")
w("Papers with no abstract are listed with metadata only — treat them as unusable evidence.")
w("")
w("---")
w("")
for i, (p, fc) in enumerate(zip(rows, ftcells), 1):
    key = (p.get("doi") or p.get("unique_id") or p.get("title", ""))[:200].lower()
    e = eid_by_doi.get(key)
    ex = extra.get(key)
    hdr = f"## P{i}" + (f" (= {e})" if e else "") + f" — {p.get('title')}"
    w(hdr)
    w("")
    meta = [f"**DOI:** `{p.get('doi')}`" if p.get("doi") else "**DOI:** none"]
    if name_of(p.get("journal")): meta.append(f"**Journal:** {name_of(p.get('journal'))}")
    if p.get("date"): meta.append(f"**Date:** {p.get('date')}")
    if p.get("publication_type"): meta.append(f"**Type:** {p.get('publication_type')}")
    w("  ·  ".join(meta))
    w("")
    au = authors(p.get("authors"))
    if au:
        w(f"**Authors:** {', '.join(au[:6])}")
        w("")
    if ex:
        w(f"**In section evidence sets:** {', '.join(sorted(set(ex['sections'])))}")
        w("")
    ab = p.get("abstract")
    w("**Abstract**")
    w("")
    w("> " + (ab.replace("\n", "\n> ") if ab else "_no abstract available_"))
    w("")
    for nm, val in fc.items():
        # Relevance is the pipeline's own inclusion verdict, not source content.
        # Showing it invites the verifier to inherit the filtering decision it is
        # meant to audit, and the scores are unreliable besides.
        if nm.strip().lower() == "relevance":
            continue
        w(f"**{nm} (filtered table)**")
        w("")
        w("> " + val.replace("\n", "\n> "))
        w("")
    if ex:
        for nm, val in ex["cells"].items():
            if nm.endswith(":: Relevance"):
                continue
            w(f"**Criteria cell — {nm}**")
            w("")
            w("> " + val.replace("\n", "\n> "))
            w("")

text = "\n".join(out)
dest = DUMP / "adjudication_pack_cea2bed8.md"
dest.write_text(text)
print(f"{dest}  {len(text):,} chars  ~{len(text)//4:,} tokens")
print(f"papers {len(rows)}  with E id {sum(1 for p in rows if eid_by_doi.get((p.get('doi') or p.get('unique_id') or p.get('title',''))[:200].lower()))}")
