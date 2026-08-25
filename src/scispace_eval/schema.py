"""Canonical on-disk schema for a collected run.

Deliberately decoupled from the SciSpace API response shape. The API is an
implementation detail that can change; everything downstream (extractor,
verifier, metrics) reads these models only.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

SCHEMA_VERSION = 1


class PaperRow(BaseModel):
    """One row of the enriched paper table, as the agent saw it."""

    position: int
    title: str
    authors: str | None = None
    year: int | None = None
    doi: str | None = None
    journal: str | None = None
    # criterion column name -> extracted cell text. This is the stage-4 output
    # and the pivot the whole two-hop attribution depends on.
    cells: dict[str, str] = Field(default_factory=dict)


class Criterion(BaseModel):
    """A criterion column the agent chose to build, plus the prompt that filled it."""

    name: str
    extraction_prompt: str | None = None
    used_full_text: bool | None = None
    # False for built-in table columns (Relevance, Abstract). Only derived
    # columns represent the comparison the user actually asked for, so the
    # criteria-fidelity eval must not credit the built-ins.
    derived: bool = True


class ToolCall(BaseModel):
    step: int
    agent: str | None = None
    tool: str
    args: dict[str, Any] = Field(default_factory=dict)
    result_chars: int = 0


class Retrieval(BaseModel):
    """Stage 1-2 summary: what was searched and how much survived consolidation."""

    sources_queried: list[str] = Field(default_factory=list)
    queries: list[str] = Field(default_factory=list)
    total_papers: int | None = None
    papers_read: int | None = None


class Completeness(BaseModel):
    """Why a run is or isn't usable. Dropped runs are counted, never silently included."""

    has_report: bool = False
    has_table: bool = False
    has_criteria: bool = False
    rows_with_doi: int = 0
    usable: bool = False
    reasons: list[str] = Field(default_factory=list)


class Run(BaseModel):
    schema_version: int = SCHEMA_VERSION
    thread_id: str
    run_id: str | None = None
    created_at: str | None = None
    user_query: str | None = None
    report_markdown: str | None = None
    report_path: str | None = None
    criteria: list[Criterion] = Field(default_factory=list)
    papers: list[PaperRow] = Field(default_factory=list)
    retrieval: Retrieval = Field(default_factory=Retrieval)
    tool_calls: list[ToolCall] = Field(default_factory=list)
    completeness: Completeness = Field(default_factory=Completeness)


class SourceRecord(BaseModel):
    """External ground truth for one paper. Fetched outside the pipeline under test."""

    doi: str
    resolved_by: list[str] = Field(default_factory=list)
    title: str | None = None
    year: int | None = None
    venue: str | None = None
    type: str | None = None
    is_peer_reviewed: bool | None = None
    abstract: str | None = None
    abstract_source: str | None = None
    status: Literal["resolved", "unresolved", "malformed"] = "unresolved"
