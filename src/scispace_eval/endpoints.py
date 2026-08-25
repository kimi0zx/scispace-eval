"""Endpoint paths for the SciSpace API.

Two separate services, and the split is not obvious: thread listing and artefacts
come from the product API, while the run state that carries the message and
tool-call history comes from the LangGraph runtime proxied at /langgraph.
`/api/scispace-agent/threads/{id}/state` returns 404.
"""

from __future__ import annotations

from . import config

THREAD = config.API_BASE + "/threads/{tid}"
ARTIFACTS = config.API_BASE + "/threads/{tid}/artifacts"
STATE = config.LANGGRAPH_BASE + "/threads/{tid}/state"
