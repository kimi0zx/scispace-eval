"""The four invariants that decide whether a rate can be trusted."""

from __future__ import annotations

from scispace_eval.pipeline.score import score

QUOTE = "wearables reduced admissions by 20%"


def pack(*sources: tuple[str, str | None]) -> str:
    """An evidence pack in the shape render.py emits.

    Each source is (id, abstract) where abstract=None means the pack carries only
    the pipeline's own extracted cell for it.
    """
    out = ["# THE EVIDENCE", ""]
    for sid, abstract in sources:
        out += [f"## {sid} — A paper", "", "**Abstract**", ""]
        out += [f"> {abstract}" if abstract else "> _no abstract available_", ""]
        out += [f"**Extracted data cell — {sid} :: Findings**", "", "> a summary of the paper", ""]
    return "\n".join(out)


def claim(cid: str, severity: str = "P0", restates: str | None = None) -> dict:
    return {"id": cid, "claim": "c", "verbatim": "v", "section": "s",
            "type": "numeric", "severity": severity, "restates": restates}


def verdict(cid: str, label: str, quote: str = QUOTE, ev: list[str] | None = None) -> dict:
    return {"id": cid, "verdict": label, "evidence_ids": ev if ev is not None else ["P1"],
            "quote": quote, "quote_field": "abstract", "source_measured": "x",
            "claim_presents_as": "y", "value_check": "exact", "reason": "r",
            "search_note": None}


def test_restatement_chain_keeps_the_failing_instance():
    """Three claims, one assertion. Collapsing must not hide the failure."""
    claims = [claim("c1"), claim("c2", restates="c1"), claim("c3", restates="c2")]
    verdicts = [verdict("c1", "verified"), verdict("c2", "verified"),
                verdict("c3", "miscited")]

    s = score("t", claims, verdicts, pack(("P1", QUOTE)))

    assert s.claims == 3
    assert s.assertions == 1, "a restatement chain is one assertion"
    assert s.overall.blocking == 1, "the failing instance must represent the group"
    assert s.overall.verified == 0
    assert s.gate == "BLOCK"


def test_paraphrased_quote_voids_the_verdict():
    """A quote that is not a literal span of the pack cannot be audited."""
    claims = [claim("c1"), claim("c2")]
    verdicts = [verdict("c1", "verified", quote=QUOTE),
                verdict("c2", "verified", quote="wearables cut admissions by about a fifth")]

    s = score("t", claims, verdicts, pack(("P1", QUOTE)))

    assert s.overall.verified == 1, "only the literal quote counts"
    assert s.overall.void == 1
    assert s.integrity["quote_not_in_evidence"] == ["c2"]


def test_failure_on_a_source_with_no_text_is_downgraded():
    """P2 offers only the pipeline's own cell, so a failure against it proves nothing."""
    claims = [claim("c1"), claim("c2")]
    verdicts = [verdict("c1", "miscited", ev=["P1"]),
                verdict("c2", "miscited", ev=["P2"])]

    s = score("t", claims, verdicts, pack(("P1", QUOTE), ("P2", None)))

    assert s.overall.blocking == 1, "only the auditable source keeps its failure"
    assert s.overall.unverifiable == 1
    assert s.integrity["downgraded_unauditable_source"] == ["c2"]


def test_gate_blocks_on_p0_miscite_but_not_on_overstatement():
    """overstated is tracked, not gated, at any severity."""
    ev = pack(("P1", QUOTE))

    tracked = score("t", [claim("c1", "P0")], [verdict("c1", "overstated")], ev)
    assert tracked.overall.quality == 1
    assert tracked.gate == "PASS", "over-generalisation must not block a release"

    blocked = score("t", [claim("c1", "P0")], [verdict("c1", "miscited")], ev)
    assert blocked.gate == "BLOCK"
    assert blocked.rows["P0"].blocking_ids == ["c1"]

    # the same miscite below P0 is recorded as a failure but does not gate
    lower = score("t", [claim("c1", "P2")], [verdict("c1", "miscited")], ev)
    assert lower.rows["P2"].blocking == 1, "still a factual error"
    assert lower.gate == "PASS", "nothing a reader acts on depends on it"
