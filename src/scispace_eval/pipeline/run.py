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
from .. import endpoints
from ..http import Client
from . import agent, render, report
from .score import score

log = logging.getLogger(__name__)


def _workdir(thread_id: str) -> Path:
    d = config.PIPELINE_DIR / thread_id
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
    bundle["thread"] = c.get_json(endpoints.THREAD.format(tid=thread_id), allow_404=True)
    bundle["state"] = c.get_json(endpoints.STATE.format(tid=thread_id), allow_404=True)
    arts = c.get_json(endpoints.ARTIFACTS.format(tid=thread_id), allow_404=True) or {}
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
    d = _workdir(thread_id)
    pack = (d / "prompt_verifier.md").read_text()
    result = score(thread_id, claims, verdicts, pack).as_dict()
    (d / "summary.json").write_text(json.dumps(result, indent=2))
    return result


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
