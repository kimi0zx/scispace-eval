from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from .. import config
from ..http import AuthExpired
from ..schema import SourceRecord
from ..pipeline.run import pipeline
from . import groundtruth, threads
from .normalize import normalize

app = typer.Typer(add_completion=False, help="Phase 0: evidence acquisition.")
console = Console()
log = logging.getLogger(__name__)


@app.callback()
def _setup(verbose: bool = False) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    config.ensure_dirs()


@app.command()
def probe(thread_id: str) -> None:
    """Confirm which candidate API paths work, using one known thread."""
    try:
        found = threads.probe(threads.client(), thread_id)
    except AuthExpired as exc:
        console.print(f"[red]auth rejected[/red] {exc}")
        raise typer.Exit(1) from exc
    for name, path in found.items():
        mark = "[green]ok[/green]" if path else "[red]none of the candidates[/red]"
        console.print(f"{name:10} {mark}  {path or ''}")


@app.command("list")
def list_cmd(limit: int = 100, page_size: int = 20) -> None:
    """List available threads."""
    c = threads.client()
    rows = []
    for item in threads.list_threads(c, page_size=page_size):
        rows.append(item)
        if len(rows) >= limit:
            break
    out = config.RAW_DIR / "threads_index.json"
    out.write_text(json.dumps(rows, indent=2))

    t = Table("thread_id", "title", "created")
    for r in rows[:40]:
        t.add_row(
            (threads.thread_id_of(r) or "?")[:36],
            str(r.get("title") or r.get("name") or "")[:60],
            str(r.get("created_at") or r.get("updated_at") or "")[:19],
        )
    console.print(t)
    console.print(f"{len(rows)} threads -> {out}")


@app.command()
def fetch(
    thread_id: list[str] = typer.Argument(None),
    from_index: bool = typer.Option(False, help="Fetch every thread in threads_index.json"),
    force: bool = False,
) -> None:
    """Fetch raw state and artefacts for one or more threads."""
    ids = list(thread_id or [])
    if from_index:
        idx = config.RAW_DIR / "threads_index.json"
        if not idx.exists():
            console.print("[red]no threads_index.json[/red] - run `list` first")
            raise typer.Exit(1)
        ids += [
            tid
            for tid in (threads.thread_id_of(r) for r in json.loads(idx.read_text()))
            if tid
        ]
    if not ids:
        console.print("[red]nothing to fetch[/red]")
        raise typer.Exit(1)

    c = threads.client()
    for tid in dict.fromkeys(ids):
        try:
            threads.fetch_raw(c, tid, force=force)
            console.print(f"[green]fetched[/green] {tid}")
        except AuthExpired as exc:
            console.print(f"[red]auth rejected[/red] {exc}")
            raise typer.Exit(1) from exc
        except Exception as exc:  # noqa: BLE001 - one bad thread must not kill the batch
            console.print(f"[yellow]skipped[/yellow] {tid}: {exc}")


@app.command("normalize")
def normalize_cmd(raw_file: list[Path] = typer.Argument(None)) -> None:
    """Parse raw bundles into canonical runs. Unusable runs are reported, not dropped silently."""
    files = list(raw_file or sorted(config.RAW_DIR.glob("*.json")))
    files = [f for f in files if f.name != "threads_index.json"]
    if not files:
        console.print("[red]no raw bundles[/red] - run `fetch` first")
        raise typer.Exit(1)

    t = Table("thread", "papers", "dois", "criteria", "report", "usable", "why not")
    usable = 0
    for f in files:
        bundle = json.loads(f.read_text())
        state = bundle.get("state") if "state" in bundle else bundle
        tid = bundle.get("thread_id") or f.stem
        run = normalize(tid, state)
        (config.RUNS_DIR / f"{tid}.json").write_text(run.model_dump_json(indent=2))
        usable += run.completeness.usable
        t.add_row(
            tid[:12],
            str(len(run.papers)),
            str(run.completeness.rows_with_doi),
            str(sum(1 for c in run.criteria if c.derived)),
            f"{len(run.report_markdown or '')}c",
            "yes" if run.completeness.usable else "no",
            ", ".join(run.completeness.reasons),
        )
    console.print(t)
    console.print(f"{usable}/{len(files)} usable -> {config.RUNS_DIR}")


@app.command("ground-truth")
def ground_truth(
    run_file: list[Path] = typer.Argument(None),
    abstracts: bool = typer.Option(True, help="Also fetch abstracts (slow, rate-limited)"),
) -> None:
    """Resolve every cited DOI against two registries and fetch abstracts."""
    files = list(run_file or sorted(config.RUNS_DIR.glob("*.json")))
    if not files:
        console.print("[red]no normalized runs[/red] - run `normalize` first")
        raise typer.Exit(1)

    dois: dict[str, None] = {}
    for f in files:
        run = json.loads(f.read_text())
        for p in run.get("papers") or []:
            raw = p.get("doi")
            if raw:
                dois[raw] = None

    ex = groundtruth.existence_client()
    ab = groundtruth.abstract_client() if abstracts else None
    records: list[SourceRecord] = []
    interactive = sys.stdout.isatty()
    for i, doi in enumerate(dois, 1):
        if interactive:
            console.print(f"[dim]{i}/{len(dois)}[/dim] {doi}", end="\r")
        records.append(groundtruth.resolve(doi, ex, ab))

    out = config.OUT_DIR / "sources.json"
    out.write_text(json.dumps([r.model_dump() for r in records], indent=2))

    resolved = [r for r in records if r.status == "resolved"]
    both = [r for r in resolved if len(r.resolved_by) == 2]
    one = [r for r in resolved if len(r.resolved_by) == 1]
    console.print(f"total DOIs          {len(records)}")
    console.print(f"resolved            {len(resolved)}  (both registries {len(both)}, one {len(one)})")
    console.print(f"unresolved          {sum(1 for r in records if r.status == 'unresolved')}")
    console.print(f"malformed           {sum(1 for r in records if r.status == 'malformed')}")
    console.print(f"not peer reviewed   {sum(1 for r in records if r.is_peer_reviewed is False)}")
    if abstracts:
        console.print(f"abstracts obtained  {sum(1 for r in records if r.abstract)}")
    console.print(f"-> {out}")
    if one:
        console.print(
            "[yellow]note[/yellow] single-registry resolutions would be false "
            "fabrication flags under one-source validation: "
            + ", ".join(r.doi for r in one[:5])
        )


if __name__ == "__main__":
    app()


@app.command()
def stats() -> None:
    """Corpus report: what was collected, what was dropped and why."""
    import collections

    files = sorted(config.RUNS_DIR.glob("*.json"))
    if not files:
        console.print("[red]no normalized runs[/red] - run `normalize` first")
        raise typer.Exit(1)
    runs = [json.loads(f.read_text()) for f in files]
    usable = [r for r in runs if r["completeness"]["usable"]]
    dropped = [r for r in runs if not r["completeness"]["usable"]]

    console.print(f"[bold]threads collected[/bold]  {len(runs)}")
    console.print(f"[bold]usable runs[/bold]        {len(usable)}")

    # A thread that never called write_report is not a report-writing run. That
    # is a corpus filter, not a product failure, and the two must not be pooled.
    def attempted(r: dict) -> bool:
        return any(t["tool"] == "write_report" for t in r["tool_calls"])

    not_reports = [r for r in dropped if not attempted(r)]
    broken = [r for r in dropped if attempted(r)]
    console.print(f"[bold]not report runs[/bold]    {len(not_reports)}  (excluded, no write_report call)")
    console.print(f"[bold]report runs dropped[/bold] {len(broken)}  (attempted a report, evidence chain incomplete)")

    if broken:
        t = Table("thread", "papers", "criteria", "report", "why")
        for r in broken:
            t.add_row(
                r["thread_id"][:8],
                str(len(r["papers"])),
                str(sum(1 for c in r["criteria"] if c["derived"])),
                f"{len(r['report_markdown'] or '')}c",
                ", ".join(r["completeness"]["reasons"]),
            )
        console.print(t)

    rows = sum(len(r["papers"]) for r in usable)
    retrieved = sum(r["retrieval"]["total_papers"] or 0 for r in usable)
    dois = {p["doi"] for r in usable for p in r["papers"] if p.get("doi")}
    console.print("")
    console.print(f"table rows          {rows}")
    console.print(f"unique cited DOIs   {len(dois)}")
    console.print(f"report characters   {sum(len(r['report_markdown'] or '') for r in usable):,}")
    if retrieved:
        console.print(
            f"retrieval funnel    {retrieved} retrieved -> {rows} read "
            f"([bold]{rows / retrieved:.1%}[/bold] of retrieved literature reached a report)"
        )

    crit = collections.Counter(sum(1 for c in r["criteria"] if c["derived"]) for r in usable)
    console.print(f"derived criteria    {dict(sorted(crit.items()))}")
    ft = collections.Counter(
        c["used_full_text"] for r in usable for c in r["criteria"] if c["derived"]
    )
    console.print(f"use_full_text       {dict(ft)}")


@app.command()
def verify(
    thread_id: str = typer.Argument(..., help="SciSpace thread id to evaluate"),
    model: str = typer.Option(None, help="Model override passed to the Claude CLI"),
    force: bool = typer.Option(False, help="Ignore cached stages and rerun"),
    stop_after: str = typer.Option(None, help="Stop early: 'extract' or 'claims'"),
) -> None:
    """Full pipeline: thread id in, verification output out.

    Needs SCISPACE_COOKIE in the environment or in .env, and the `claude` CLI on PATH.
    """
    try:
        result = pipeline(thread_id, model=model, force=force, stop_after=stop_after)
    except Exception as exc:  # noqa: BLE001 - surface the cause, not a traceback
        console.print(f"[red]{type(exc).__name__}[/red] {exc}")
        raise typer.Exit(1) from exc

    if result.get("skipped"):
        console.print(f"[yellow]skipped[/yellow] {result['skipped']}")
        return
    if "verdict_counts" not in result:
        console.print(json.dumps(result, indent=2))
        return

    console.print(f"[bold]claims[/bold]   {result['claims']}")
    console.print(f"[bold]verdicts[/bold] {result['verdicts']}")
    console.print("")
    t = Table("verdict", "n")
    for k, n in (result["verdict_counts"] or {}).items():
        t.add_row(str(k), str(n))
    console.print(t)


    LABELS = ("verified", "unfounded", "miscited", "overstated", "unverifiable")
    t = Table("severity", *LABELS)
    for sev in sorted(result["by_severity"]):
        row = result["by_severity"][sev]
        t.add_row(sev, *[str(row.get(k, 0)) for k in LABELS])
    console.print(t)

    if result["p0_p1_rate"] is not None:
        console.print(
            f"[bold]P0/P1 not verified[/bold] {result['p0_p1_failed']}/"
            f"{result['p0_p1_total']} = [bold]{result['p0_p1_rate']:.1%}[/bold]"
            "  [dim](unverifiable excluded)[/dim]"
        )
    if result["unexpected_labels"]:
        console.print(f"[red]unexpected labels[/red] {', '.join(result['unexpected_labels'])}")

    integ = result["integrity"]
    for label, ids in (
        ("quotes not found in evidence", integ["quotes_not_in_evidence"]),
        ("supported but reason names a mismatch", integ["supported_but_reason_names_mismatch"]),
    ):
        if ids:
            console.print(f"[red]integrity[/red] {label}: {', '.join(ids[:12])}")
    if result["missing_verdicts"]:
        console.print(f"[red]missing verdicts[/red] {', '.join(result['missing_verdicts'][:12])}")

    console.print(f"\n-> {config.DATA_DIR / 'pipeline' / thread_id}")
