"""Score a run's verdicts.

This is the only place a rate is computed, because two things have to happen
before a verdict may be counted and both are easy to skip:

  * the quote must be a literal span of the evidence pack. A verdict whose quote
    cannot be found is void, not merely suspect: a paraphrased quote cannot be
    audited, so counting it asserts something unfalsifiable.
  * restated assertions must collapse. Reports state a headline figure in the
    introduction, again in the body, again in the conclusion. Each instance is a
    real claim, but they are one assertion, and counting four turns one error
    into four.
"""

from __future__ import annotations

import collections
import json
from dataclasses import dataclass, field
from pathlib import Path

LABELS = ("verified", "unfounded", "miscited", "overstated", "unverifiable")
LEVELS = ("P0", "P1", "P2")

# A failure is the report claiming more than its sources carry. `unverifiable` is
# an evidence-access limit on our side and never counts against the product.
FAILING = ("unfounded", "miscited", "overstated")

# Blocking is the subset that is factually wrong rather than badly calibrated.
# `overstated` is tracked, not gated: over-generalisation is endemic to
# summarisation, so gating on it would block every release.
BLOCKING = ("unfounded", "miscited")

# Phrases that mean the verifier could not confirm something. A failure verdict
# whose reason contains one is self-contradictory and is reported, not trusted.
HEDGES = (
    "cannot be confirmed", "could not be confirmed", "cannot confirm",
    "no abstract", "not available", "could not be established",
)

NO_ABSTRACT = "_no abstract available_"


@dataclass
class Row:
    level: str
    total: int = 0
    verified: int = 0
    blocking: int = 0
    quality: int = 0
    unverifiable: int = 0
    void: int = 0
    blocking_ids: list[str] = field(default_factory=list)
    quality_ids: list[str] = field(default_factory=list)

    @property
    def judged(self) -> int:
        return self.verified + self.blocking + self.quality


@dataclass
class Score:
    thread_id: str
    rows: dict[str, Row]
    overall: Row
    per_claim: dict[str, int]
    integrity: dict[str, list[str]]
    assertions: int
    claims: int

    @property
    def gate(self) -> str:
        return "BLOCK" if self.overall.blocking else "PASS"

    def as_dict(self) -> dict:
        def r(x: Row) -> dict:
            d = {k: getattr(x, k) for k in
                 ("total", "verified", "blocking", "quality", "unverifiable", "void")}
            d["judged"] = x.judged
            d["blocking_rate"] = round(x.blocking / x.judged, 4) if x.judged else None
            d["failure_rate"] = round((x.blocking + x.quality) / x.judged, 4) if x.judged else None
            d["blocking_ids"] = x.blocking_ids
            d["quality_ids"] = x.quality_ids
            return d
        return {
            "thread_id": self.thread_id,
            "claims": self.claims,
            "distinct_assertions": self.assertions,
            "gate": self.gate,
            "by_severity": {k: r(v) for k, v in self.rows.items()},
            "overall": r(self.overall),
            "verdict_counts_per_claim": self.per_claim,
            "integrity": self.integrity,
        }


def sources_without_abstract(evidence_pack: str) -> set[str]:
    """Source ids whose only text in the pack is the pipeline's own extracted cells.

    A verdict resting solely on these cannot be confirmed: the cells are LLM
    summaries of full text the harness never sees, so judging a claim against them
    means grading the pipeline against its own output.
    """
    import re

    out: set[str] = set()
    for m in re.finditer(r"\n## (P\d+) ", evidence_pack):
        nxt = re.search(r"\n## P\d+ ", evidence_pack[m.end():])
        block = evidence_pack[m.start(): m.end() + (nxt.start() if nxt else 4000)]
        head = block.split("**Extracted data cell", 1)[0]
        if NO_ABSTRACT in head:
            out.add(m.group(1))
    return out


def _root(cid: str, claims: dict[str, dict]) -> str:
    """Follow a restatement chain to the assertion's first occurrence."""
    seen: set[str] = set()
    while True:
        parent = claims.get(cid, {}).get("restates")
        if not parent or parent not in claims or parent in seen:
            return cid
        seen.add(cid)
        cid = parent


def score(
    thread_id: str,
    claims: list[dict],
    verdicts: list[dict],
    evidence_pack: str,
) -> Score:
    by_id = {c["id"]: c for c in claims}
    v = {x["id"]: dict(x) for x in verdicts}

    unauditable = sources_without_abstract(evidence_pack)

    integrity: dict[str, list[str]] = {
        "quote_not_in_evidence": [],
        "unexpected_label": [],
        "reason_contradicts_verdict": [],
        "downgraded_no_abstract": [],
        "missing_verdict": sorted(set(by_id) - set(v)),
        "verdict_without_claim": sorted(set(v) - set(by_id)),
    }

    for cid, x in v.items():
        label = x.get("verdict")
        if label not in LABELS:
            integrity["unexpected_label"].append(cid)

        quote = x.get("quote") or ""
        x["_receipt"] = bool(quote) and quote in evidence_pack
        if not x["_receipt"] and label != "unverifiable":
            integrity["quote_not_in_evidence"].append(cid)

        reason = (x.get("reason") or "").lower()
        if label in FAILING and any(h in reason for h in HEDGES):
            integrity["reason_contradicts_verdict"].append(cid)

        # A failure asserted only against sources with no abstract rests on the
        # pipeline's own summary. That is not evidence of a defect, so downgrade
        # rather than count it.
        ids = x.get("evidence_ids") or []
        if label in FAILING and ids and all(e in unauditable for e in ids):
            integrity["downgraded_no_abstract"].append(cid)
            x["verdict"] = label = "unverifiable"

        # A verdict is countable only if it reached a determination and can be
        # audited. Everything else is reported, never silently folded in.
        x["_countable"] = x["_receipt"] and label != "unverifiable"

    # One representative per assertion. Prefer a blocking instance, then any
    # failure, then a countable one, so collapsing can never hide an error.
    def rank(cid: str) -> tuple:
        x = v.get(cid, {})
        label = x.get("verdict")
        return (label in BLOCKING, label in FAILING, bool(x.get("_countable")))

    chosen: dict[str, str] = {}
    for cid in by_id:
        r = _root(cid, by_id)
        if r not in chosen or rank(cid) > rank(chosen[r]):
            chosen[r] = cid
    reps = list(chosen.values())

    rows = {lvl: Row(lvl) for lvl in LEVELS}
    overall = Row("ALL")
    for cid in reps:
        lvl = by_id[cid].get("severity")
        row = rows.get(lvl)
        x = v.get(cid, {})
        label = x.get("verdict")
        for target in (row, overall):
            if target is None:
                continue
            target.total += 1
            if label == "unverifiable":
                target.unverifiable += 1
            elif not x.get("_receipt"):
                target.void += 1
            elif label in BLOCKING:
                target.blocking += 1
                target.blocking_ids.append(cid)
            elif label == "overstated":
                target.quality += 1
                target.quality_ids.append(cid)
            elif label == "verified":
                target.verified += 1

    return Score(
        thread_id=thread_id,
        rows=rows,
        overall=overall,
        per_claim=dict(collections.Counter(x.get("verdict") for x in v.values())),
        integrity={k: sorted(set(val)) for k, val in integrity.items()},
        assertions=len(reps),
        claims=len(claims),
    )


def load_and_score(run_dir: Path) -> Score:
    """Score a completed pipeline run from its own output files."""
    import re

    def block(path: Path) -> list[dict]:
        blocks = re.findall(r"```json\s*(\[.*?\])\s*```", path.read_text(), re.S)
        if not blocks:
            raise ValueError(f"{path}: no fenced json array")
        return json.loads(max(blocks, key=len))

    return score(
        run_dir.name,
        block(run_dir / "claims.md"),
        block(run_dir / "verdicts.md"),
        (run_dir / "prompt_verifier.md").read_text(),
    )
