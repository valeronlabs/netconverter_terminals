"""Noninteractive adapters for the revisioned draft contract.

YAML is transferred directly between the workspace and the authenticated API.
These commands do not instantiate an AI provider or record human approval.
"""

from __future__ import annotations

import json

from .workspace import Workspace


def _revision(value: str) -> int:
    import argparse

    try:
        revision = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("revision must be a positive integer") from None
    if revision < 1:
        raise argparse.ArgumentTypeError("revision must be a positive integer")
    return revision


def add_parser(subparsers):
    draft = subparsers.add_parser("draft", help="prepare and review a revisioned migration draft")
    commands = draft.add_subparsers(dest="draft_command", required=True)
    commands.add_parser("catalog", help="show design operations and qualification gaps")
    context = commands.add_parser("context", help="show bounded interface facts and proposed mappings")
    context.add_argument("draft_id")
    context.add_argument("--revision", type=_revision, required=True)
    context.add_argument("--view-id", choices=["strict", "interfaces"], default="interfaces")
    context.add_argument("--offset", type=int)
    context.add_argument("--limit", type=int)
    prepare = commands.add_parser("prepare", help="prepare a draft without executing a migration")
    prepare.add_argument("path")
    prepare.add_argument("--vendor", dest="source_vendor", default="cisco_asa")
    prepare.add_argument("--to", dest="target_vendor", default="palo_alto_set")
    prepare.add_argument("--workflow", choices=["studio", "quick"], default="studio")
    prepare.add_argument("--idempotency-key", required=True, help="reuse this key when retrying the same request")
    for name in ("decisions", "export", "import", "propose", "validate", "review", "execute"):
        command = commands.add_parser(name)
        command.add_argument("draft_id")
        command.add_argument("--revision", type=_revision, required=True)
        if name not in {"decisions", "export"}:
            command.add_argument("--idempotency-key", required=True)
        if name == "import":
            command.add_argument("--yaml", dest="yaml_path", required=True,
                                 help="local YAML path inside the workspace; uploaded directly")
        if name == "propose":
            command.add_argument("--changes", required=True,
                                 help="JSON typed operations from draft catalog, or opaque decision choices")
        if name == "execute":
            command.add_argument("--approval-ref", required=True,
                                 help="reference issued after independent human review of this revision")
    for name in ("job-status", "download-result"):
        command = commands.add_parser(name, help="inspect a draft execution" if name == "job-status"
                                      else "download one verified artifact from a draft execution")
        command.add_argument("job_id")
        command.add_argument("--draft-id", required=True)
        command.add_argument("--revision", type=_revision, required=True)
        if name == "download-result":
            command.add_argument("--artifact-id", required=True)
            command.add_argument("--manifest-revision", type=_revision, required=True)
    return draft


def run(args, credential) -> dict:
    from .drafts import DraftClient, DraftService

    actions = {
        "context": "read_context", "catalog": "get_design_catalog", "prepare": "prepare_draft", "decisions": "get_required_decisions",
        "export": "export_document", "import": "propose_changes", "propose": "propose_changes",
        "validate": "validate_draft", "review": "request_review", "execute": "execute_approved",
        "job-status": "get_job_status", "download-result": "download_artifact",
    }
    fields = ("path", "source_vendor", "target_vendor", "workflow", "idempotency_key",
              "draft_id", "revision", "yaml_path", "approval_ref", "job_id", "artifact_id",
              "manifest_revision", "view_id", "offset", "limit")
    arguments = {name: getattr(args, name) for name in fields if hasattr(args, name) and getattr(args, name) is not None}
    if args.draft_command == "propose":
        try:
            if len(args.changes) > 32_000:
                raise ValueError()
            arguments["changes"] = json.loads(args.changes)
        except (ValueError, TypeError):
            return {"schema_version": "1", "ok": False, "error": {
                "code": "invalid_arguments", "message": "Provide a bounded JSON array of decision choices."
            }}
    client = None
    try:
        workspace = Workspace(args.workspace)
        client = DraftClient(credential, args.server)
        return DraftService(workspace, client).call(actions[args.draft_command], arguments)
    except (ValueError, OSError, RuntimeError):
        return {"schema_version": "1", "ok": False, "error": {
            "code": "invalid_arguments", "message": "The draft operation is unavailable; check the workspace and server settings."
        }}
    finally:
        if client is not None:
            client.close()
