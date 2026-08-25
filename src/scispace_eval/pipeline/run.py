"""thread id -> verification output.

Five stages, each cached on disk so a rerun resumes rather than repeats:

  1 collect    fetch thread state, artefact list and artefact contents
  2 extract    recover the report and build the evidence set
  3 claims     agent 1 reads the report alone and emits the claim ledger
  4 verify     agent 2 checks each claim against the evidence
  5 summarise  roll the verdicts up

Agents 1 and 2 are separate on purpose. Showing the evidence to the extractor
biases it toward claims it can already tell are provable, which understates the
report's exposure.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from pathlib import Path

from .. import config
from ..collect import threads
from ..http import Client
from . import agent, render, report

log = logging.getLogger(__name__)


def _workdir(thread_id: str) -> Path:
    d = config.DATA_DIR / "pipeline" / thread_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def collect(thread_id: str, force: bool = False) -> dict:
    """Fetch everything scrapable for a thread, including artefact contents."""
    out = _workdir(thread_id) / "bundle.json"
    if out.exists() and not force:
        log.info("bundle cached: %s", out)
        return json.loads(out.read_text())

    c = Client(headers=config.credentials().headers(), min_interval=0.2)
    bundle: dict = {"thread_id": thread_id}
    bundle["thread"] = c.get_json(f"{config.API_BASE}/threads/{thread_id}", allow_404=True)
    bundle["state"] = c.get_json(
        f"{config.LANGGRAPH_BASE}/threads/{thread_id}/state", allow_404=True
    )
    arts = c.get_json(f"{config.API_BASE}/threads/{thread_id}/artifacts", allow_404=True) or {}
    bundle["artifacts"] = arts

    files: dict[str, dict] = {}
    for a in arts.get("data", []):
        path = a["sandbox_path"]
        try:
            r = c.session.get(a["serve_url"], timeout=120)
            files[path] = {
                "status": r.status_code,
                "bytes": len(r.content),
                "mime": a.get("mime_type"),
                "text": r.text if r.status_code == 200 else "",
            }
        except Exception as exc:  # noqa: BLE001 - one bad artefact must not kill the run
            log.warning("artefact fetch failed %s: %s", path, exc)
            files[path] = {"status": "ERR", "bytes": 0, "mime": a.get("mime_type"), "text": ""}
    bundle["files"] = files
    out.write_text(json.dumps(bundle, indent=2, ensure_ascii=False))
    log.info("collected %d artefacts -> %s", len(files), out)
    return bundle


def extract(thread_id: str, bundle: dict) -> report.Extraction:
    ex = report.extract(bundle)
    d = _workdir(thread_id)
    (d / "report_clean.md").write_text(ex.report_markdown or "")
    (d / "evidence.json").write_text(
        json.dumps([asdict(p) for p in ex.papers], indent=2, ensure_ascii=False)
    )
    (d / "extraction_meta.json").write_text(
        json.dumps(
            {
                "mode": ex.mode,
                "report_chars": len(ex.report_markdown or ""),
                "papers": len(ex.papers),
                "papers_with_abstract": sum(1 for p in ex.papers if p.abstract),
                "papers_with_fulltext_url": sum(1 for p in ex.papers if p.fulltext_url),
                "sections_self_verified": ex.section_count,
                "self_verification": ex.self_verification,
                "corrections": len(ex.corrections),
                "notes": ex.notes,
            },
            indent=2,
        )
    )
    log.info(
        "mode=%s report=%d chars evidence=%d papers (%d with abstract)",
        ex.mode, len(ex.report_markdown or ""), len(ex.papers),
        sum(1 for p in ex.papers if p.abstract),
    )
    return ex


def run_extractor(thread_id: str, ex: report.Extraction, model: str | None, force: bool) -> list[dict]:
    d = _workdir(thread_id)
    dest = d / "claims.md"
    if dest.exists() and not force:
        log.info("claims cached: %s", dest)
        return render.parse_json_block(dest)

    prompt = render.extractor_prompt(ex, d / "prompt_extractor.md", dest)
    res = agent.run(prompt, model=model, cwd=d)
    if not dest.exists():
        raise agent.AgentError(f"extractor produced no output at {dest}: {res.text[:400]}")
    claims = render.parse_json_block(dest)
    log.info("extracted %d claims (cost $%s)", len(claims), res.cost_usd)
    return claims


def run_verifier(
    thread_id: str, claims: list[dict], ex: report.Extraction, model: str | None, force: bool
) -> list[dict]:
    d = _workdir(thread_id)
    dest = d / "verdicts.md"
    if dest.exists() and not force:
        log.info("verdicts cached: %s", dest)
        return render.parse_json_block(dest)

    prompt = render.verifier_prompt(claims, ex.papers, d / "prompt_verifier.md", dest)
    res = agent.run(prompt, model=model, cwd=d)
    if not dest.exists():
        raise agent.AgentError(f"verifier produced no output at {dest}: {res.text[:400]}")
    verdicts = render.parse_json_block(dest)
    log.info("verified %d claims (cost $%s)", len(verdicts), res.cost_usd)
    return verdicts


def summarise(thread_id: str, claims: list[dict], verdicts: list[dict]) -> dict:
    import collections

    by_id = {c["id"]: c for c in claims}
    v = {x["id"]: x for x in verdicts}
    missing = sorted(set(by_id) - set(v))
    extra = sorted(set(v) - set(by_id))

    # Integrity checks. A quote that is not a literal substring of the evidence
    # means the verifier invented its justification, and a `supported` verdict
    # whose reason names a mismatch is the failure that produced the last run's
    # false negatives -- both are checked mechanically rather than trusted.
    d = _workdir(thread_id)
    pack = (d / "prompt_verifier.md").read_text() if (d / "prompt_verifier.md").exists() else ""
    bad_quotes = [
        x["id"] for x in verdicts
        if x.get("quote") and pack and x["quote"] not in pack
    ]
    MISMATCH = ("recurrence", "prognosis", "survival", "different", "mismatch",
                "not detection", "response to", "staging")
    inconsistent = [
        x["id"] for x in verdicts
        if x.get("verdict") == "verified"
        and any(t in (x.get("reason") or "").lower() for t in MISMATCH)
    ]

    def count(field: str, source: dict) -> dict:
        return dict(collections.Counter(source[i].get(field) for i in source))

    sev = {}
    for i, x in v.items():
        s = by_id.get(i, {}).get("severity", "?")
        sev.setdefault(s, collections.Counter())[x.get("verdict")] += 1

    LABELS = ("verified", "unfounded", "miscited", "overstated", "unverifiable")
    # `unverifiable` is an evidence-access limit on our side, not a defect in the
    # report, so it never counts toward the failure rate.
    failed = [i for i, x in v.items() if x.get("verdict") in ("unfounded", "miscited", "overstated")]
    critical = [i for i in failed if by_id.get(i, {}).get("severity") in ("P0", "P1")]
    critical_total = sum(1 for c in claims if c.get("severity") in ("P0", "P1"))

    summary = {
        "thread_id": thread_id,
        "claims": len(claims),
        "verdicts": len(verdicts),
        "missing_verdicts": missing,
        "unexpected_verdicts": extra,
        "verdict_counts": {k: count("verdict", v).get(k, 0) for k in LABELS},
        "unexpected_labels": sorted(
            {str(x.get("verdict")) for x in verdicts} - set(LABELS)
        ),
        "by_severity": {k: dict(c) for k, c in sev.items()},
        "failed": sorted(failed, key=lambda x: int(x[1:]) if x[1:].isdigit() else 0),
        "p0_p1_failed": len(critical),
        "p0_p1_total": critical_total,
        "p0_p1_rate": round(len(critical) / critical_total, 4) if critical_total else None,
        "integrity": {
            "quotes_not_in_evidence": bad_quotes,
            "supported_but_reason_names_mismatch": inconsistent,
        },
    }
    (_workdir(thread_id) / "summary.json").write_text(json.dumps(summary, indent=2))
    return summary


def pipeline(
    thread_id: str,
    *,
    model: str | None = None,
    force: bool = False,
    stop_after: str | None = None,
) -> dict:
    config.ensure_dirs()
    bundle = collect(thread_id, force=force)
    ex = extract(thread_id, bundle)
    if ex.mode == "not_a_report_run":
        return {"thread_id": thread_id, "skipped": "not a report-writing run"}
    if stop_after == "extract":
        return {"thread_id": thread_id, "mode": ex.mode, "papers": len(ex.papers)}

    claims = run_extractor(thread_id, ex, model, force)
    if stop_after == "claims":
        return {"thread_id": thread_id, "claims": len(claims)}

    verdicts = run_verifier(thread_id, claims, ex, model, force)
    return summarise(thread_id, claims, verdicts)
