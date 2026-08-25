"""Run a prompt through the Claude Code CLI in print mode.

The prompts here are 200k+ tokens, so they go via a file and `--print` reads the
prompt from stdin. Output is parsed from `--output-format json`.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)


class AgentError(RuntimeError):
    pass


@dataclass
class AgentResult:
    text: str
    cost_usd: float | None
    duration_ms: int | None
    num_turns: int | None
    session_id: str | None


def _cli() -> str:
    exe = shutil.which("claude")
    if not exe:
        raise AgentError("`claude` CLI not found on PATH")
    return exe


def run(
    prompt_file: Path,
    *,
    model: str | None = None,
    # Bash is included because agents legitimately choose to assemble large JSON
    # outputs with a throwaway script; without it they stall waiting for approval.
    allowed_tools: str = "Read,Write,Bash",
    timeout: int = 5400,
    cwd: Path | None = None,
) -> AgentResult:
    """Send a prompt file to `claude -p` and return the final text."""
    cmd = [
        _cli(),
        "--print",
        "--output-format", "json",
        "--allowed-tools", allowed_tools,
        "--permission-mode", "acceptEdits",
    ]
    if model:
        cmd += ["--model", model]

    prompt = prompt_file.read_text()
    log.info("running agent: %s (%d chars, ~%dk tokens)", prompt_file.name, len(prompt), len(prompt) // 4000)
    proc = subprocess.run(
        cmd,
        input=prompt,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=str(cwd) if cwd else None,
    )
    if proc.returncode != 0:
        raise AgentError(f"claude exited {proc.returncode}: {proc.stderr[-2000:]}")

    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise AgentError(f"could not parse CLI output: {proc.stdout[:500]}") from exc

    if isinstance(data, dict) and data.get("is_error"):
        raise AgentError(f"agent reported an error: {str(data.get('result'))[:500]}")

    return AgentResult(
        text=data.get("result") or "",
        cost_usd=data.get("total_cost_usd"),
        duration_ms=data.get("duration_ms"),
        num_turns=data.get("num_turns"),
        session_id=data.get("session_id"),
    )
