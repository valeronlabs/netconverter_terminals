"""Explicit model projection; detailed renderer data is never chat history."""

from __future__ import annotations

import re

OPERATIONS = (
    "analyze",
    "optimize",
    "convert",
    "unused_objects",
    "routes",
    "interfaces",
    "policy",
    "nat",
    "dependencies",
    "flow",
    "status",
    "artifacts",
)
COUNT_FIELDS = frozenset(
    {
        "total_objects",
        "total_unused",
        "unused_network_count",
        "unused_network_group_count",
        "unused_service_count",
        "unused_service_group_count",
        "rules",
        "routes",
        "findings",
        "total",
        "shown",
    }
)
STATUSES = frozenset(
    {
        "queued",
        "processing",
        "running",
        "completed",
        "failed",
        "cancelled",
        "passed",
        "passed_with_warnings",
        "needs_review",
        "blocked",
        "unavailable",
        "needs_input",
        "allowed",
        "denied",
        "unknown",
        "partial",
        "full",
        "empty",
    }
)
_IP = re.compile(
    r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?:/\d{1,2})?|(?<![\w:])(?:[0-9a-fA-F]{0,4}:){2,}[0-9a-fA-F:.]+(?:/\d{1,3})?"
)
_CONFIG = re.compile(
    r"(?im)^\s*(?:object(?:-group)?\s|access-list\s|interface\s|hostname\s|set\s+(?:rulebase|network|address|deviceconfig|shared)|<\??(?:xml|config)\b)"
)


def model_summary(result: dict) -> dict:
    """Never accept a server-supplied prose/summary blob as model context."""
    out: dict = {}
    for key in ("status", "translation_status", "verdict", "data_quality"):
        value = str(result.get(key, "")).lower()
        if value in STATUSES:
            out[key] = value
    for key in ("job_id", "configuration_id", "query_id"):
        value = result.get(key)
        if isinstance(value, str) and re.fullmatch(
            r"(?:tra|psc|opt|cfg|qry)_[a-f0-9]{8,40}", value
        ):
            out[key] = value
    counts = result.get("counts", {})
    if isinstance(counts, dict):
        out["counts"] = {
            key: value
            for key, value in counts.items()
            if key in COUNT_FIELDS and type(value) is int and 0 <= value <= 10**9
        }
    if result.get("requires_input") is True:
        out["status"] = "needs_input"
    return out


def safe_prompt(text: str, identifiers: list[str]) -> tuple[str, dict[str, str]]:
    if len(text) > 4000 or _CONFIG.search(text) or "```" in text:
        raise ValueError(
            "Select a config with /open; configuration text is not sent to the conversational model"
        )
    bindings: dict[str, str] = {}
    values = sorted(
        set([v for v in identifiers if v] + _IP.findall(text)), key=len, reverse=True
    )
    for value in values:
        if value in text:
            alias = f"NC_REF_{len(bindings) + 1}"
            text = text.replace(value, alias)
            bindings[alias] = value
    return text, bindings
