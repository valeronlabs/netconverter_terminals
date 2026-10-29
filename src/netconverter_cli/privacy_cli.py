"""`netconverter privacy`: the folder's exposure level for AI assistants (#13).

Terminal-only commands. Nothing here is reachable from the MCP bridge.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import exposure
from .errors import EXIT_FAILURE, EXIT_USAGE, CommandError

MEANING = {
    "none": "verdicts, statuses, counts and ids only",
    "masked": "the server's strict view: names as tokens, addresses masked (the default)",
    "selected": "masked, plus the result sections you choose",
    "full": "results as NetConverter serves them for your account",
}
SECRETS_LINE = ("Secrets (pre-shared keys, SNMP communities, password hashes, passwords) are removed "
                "from every result at every level.")


def add_parser(subparsers):
    privacy = subparsers.add_parser(
        "privacy", help="what your AI assistant may see from this folder's jobs (exposure level)")
    actions = privacy.add_subparsers(dest="privacy_command", metavar="ACTION", title="actions")
    status = actions.add_parser("status", help="show this folder's exposure level (the default action)")
    status.add_argument("--json", action="store_true", help="print the status as JSON")
    level = actions.add_parser(
        "level", help="set the level: none, masked, selected or full; raising asks for a typed confirmation")
    level.add_argument("level", choices=list(exposure.LEVELS), metavar="LEVEL",
                       help="none, masked, selected or full")
    level.add_argument("--sections", default="", metavar="LIST",
                       help="with selected: comma-separated sections: " + ", ".join(exposure.SECTIONS))
    from .privacy_apply import CLIENTS

    apply = actions.add_parser("apply", help="keep an AI client's own file tools out of this folder")
    apply.add_argument("--client", required=True, choices=list(CLIENTS), metavar="CLIENT",
                       help="assistant to configure: " + ", ".join(CLIENTS))
    apply.add_argument("--print", dest="print_only", action="store_true",
                       help="show the change without applying it")
    apply.add_argument("--yes", action="store_true", help="apply without asking (scripts)")


def run(args, ask=None) -> int:
    root = Path(args.workspace).resolve()
    action = getattr(args, "privacy_command", None) or "status"
    if action == "level":
        return _level(root, args, ask)
    if action == "apply":
        from .privacy_apply import run as run_apply

        return run_apply(root, args, ask or input)
    return _status(root, json_out=getattr(args, "json", False))


def _level(root: Path, args, ask) -> int:
    sections = [s.strip() for s in (args.sections or "").split(",") if s.strip()]
    unknown = [s for s in sections if s not in exposure.SECTIONS]
    if unknown:
        raise CommandError(f"netconverter: unknown section {unknown[0]!r}. "
                           f"Choose from: {', '.join(exposure.SECTIONS)}.", EXIT_USAGE)
    if sections and args.level != "selected":
        raise CommandError("netconverter: --sections applies only to `privacy level selected`.", EXIT_USAGE)
    try:
        old, new = exposure.set_level(root, args.level, sections, ask=ask or input)
    except exposure.ExposureError as exc:
        raise CommandError(f"netconverter: {exc}", EXIT_FAILURE) from None
    if old == new:
        print(f"Exposure level is already {new.describe()}. Nothing changed.")
    else:
        print(f"Exposure level: {old.describe()} → {new.describe()} ({MEANING[new.level]}).")
        print(f"Recorded in {exposure.audit_path(root)}. Running assistants pick it up on their next call.")
    return 0


def _status(root: Path, json_out: bool) -> int:
    current = exposure.load(root)
    stored = exposure.state_path(root).exists()
    entries = exposure.audit_entries(root, limit=10_000)
    if json_out:
        print(json.dumps({
            "level": current.level, "sections": list(current.sections),
            "source": "folder" if stored else "default", "workspace": str(root),
            "audit_log": str(exposure.audit_path(root)), "changes": len(entries),
            "levels": {level: MEANING[level] for level in exposure.LEVELS},
            "sections_available": list(exposure.SECTIONS),
        }, indent=2))
        return 0
    print(f"Exposure level: {current.describe()}" + ("" if stored else " (the default)"))
    for level in exposure.LEVELS:
        mark = "›" if level == current.level else " "
        print(f"  {mark} {level:<9} {MEANING[level]}")
    print(SECRETS_LINE)
    print(f"Folder: {root}")
    print(f"Audit log: {exposure.audit_path(root)} ({len(entries)} change{'s' if len(entries) != 1 else ''})")
    for entry in entries[-3:]:
        print(f"  {entry.get('time', '?')}  {entry.get('old', '?')} → {entry.get('new', '?')}"
              f"  by {entry.get('user', '?')}  ({entry.get('confirmed', '?')})")
    print("\nnetconverter privacy level LEVEL        change it (raising asks you to type a confirmation)")
    print("netconverter privacy apply --client X   keep that assistant's own file tools out of this folder")
    print("Sections for selected: " + ", ".join(exposure.SECTIONS))
    return 0
