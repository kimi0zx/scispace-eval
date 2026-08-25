from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from . import config
from .http import AuthExpired
from .pipeline.run import pipeline

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
def verify(
    thread_id: str = typer.Argument(..., help="SciSpace thread id to evaluate"),
    model: str = typer.Option(None, help="Model override passed to the Claude CLI"),
    force: bool = typer.Option(False, help="Ignore cached stages and rerun"),
    stop_after: str = typer.Option(None, help="Stop early: 'extract' or 'claims'"),
) -> None:
    """Full pipeline: thread id in, scored verdicts out.

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
    if "by_severity" not in result:
        console.print(json.dumps(result, indent=2))
        return

    console.print(
        f"[bold]{result['claims']}[/bold] claims "
        f"[dim]->[/dim] [bold]{result['distinct_assertions']}[/bold] distinct assertions\n"
    )
    t = Table("", "total", "verified", "blocking", "quality", "unverifiable")
    for lvl in ("P0", "P1", "P2"):
        r = result["by_severity"][lvl]
        t.add_row(
            lvl, str(r["total"]), str(r["verified"]),
            f"[red]{r['blocking']}[/red]" if r["blocking"] else "[green]0[/green]",
            str(r["quality"]), str(r["unverifiable"]),
        )
    o = result["overall"]
    t.add_row(
        "[bold]all[/bold]", f"[bold]{o['total']}[/bold]", f"[bold]{o['verified']}[/bold]",
        f"[bold red]{o['blocking']}[/bold red]" if o["blocking"] else "[bold green]0[/bold green]",
        f"[bold]{o['quality']}[/bold]", f"[bold]{o['unverifiable']}[/bold]",
    )
    console.print(t)

    gate = result["gate"]
    colour = "red" if gate == "BLOCK" else "green"
    detail = ", ".join(result["by_severity"]["P0"]["blocking_ids"]) or "no P0 unfounded or miscited claims"
    console.print(f"\n[bold {colour}]GATE {gate}[/bold {colour}]  [dim]{detail}[/dim]")

    for label, ids in result["integrity"].items():
        if ids:
            tone = "yellow" if label == "downgraded_no_abstract" else "red"
            console.print(f"[{tone}]{label}[/{tone}] {', '.join(ids[:10])}")

    console.print(f"\n[dim]{config.PIPELINE_DIR / thread_id}[/dim]")
