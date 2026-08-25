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
