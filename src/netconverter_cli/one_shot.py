"""What the one-shot `convert / validate / optimize / resume` commands print (#7).

A plain summary by default (``summary.plain_lines``); the raw API JSON with
``--json`` (as before, but without ``\\uXXXX`` escapes); every finding with ``--all``.
"""

from __future__ import annotations

import json

from .summary import plain_lines, summarize

SUMMARY_COMMANDS = frozenset({"convert", "validate", "analyze", "optimize", "resume"})


def add_flags(parser) -> None:
    parser.add_argument("--json", action="store_true", help="print the raw API response (JSON)")
    parser.add_argument("--all", action="store_true", help="list every finding, not only the first few")


def _context(controller, args, result) -> dict:
    """The operation and file a summary's next command should name."""
    job_id = result.get("job_id") if isinstance(result, dict) else None
    state = controller.state
    local = state.get("jobs", {}).get(job_id, {}) if job_id else {}
    operation = {"analyze": "validate"}.get(args.command, args.command)
    if args.command == "resume":
        operation = local.get("operation")
    configuration = state.get("configurations", {}).get(local.get("configuration_id"), {})
    return {"operation": operation, "file": getattr(args, "file", None) or configuration.get("path")}


def render(controller, args, result) -> str:
    if getattr(args, "json", False):
        return json.dumps(result, indent=2, default=str, ensure_ascii=False)
    context = _context(controller, args, result)
    every = bool(getattr(args, "all", False))
    findings = None
    if every and isinstance(result, dict) and result.get("status") == "completed" and (
            isinstance(result.get("validation"), dict) or isinstance(result.get("optimization"), dict)):
        findings = controller.findings(result["job_id"])
    names = controller.catalog.name if controller.catalog.loaded else None
    summary = summarize(result, operation=context["operation"], names=names, file=context["file"],
                        findings=findings)
    return "\n".join(plain_lines(summary, all_findings=every))
