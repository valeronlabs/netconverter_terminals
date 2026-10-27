"""Noninteractive candidate project commands using the guided transport."""
import json

from .draft_cli import _revision


def add_parser(subparsers):
    project = subparsers.add_parser("project", help="prepare a candidate multi-device project; no project execution")
    commands = project.add_subparsers(dest="project_command", required=True)
    commands.add_parser("schema")
    get = commands.add_parser("get")
    get.add_argument("project_id")
    get.add_argument("--revision", type=_revision, required=True)
    for name in ("prepare", "propose"):
        command = commands.add_parser(name)
        if name == "propose":
            command.add_argument("project_id")
            command.add_argument("--expected-revision", type=_revision, required=True)
        command.add_argument("--devices", required=True, help="JSON array of device_id, draft_id and revision references")
        command.add_argument("--links", required=True, help="JSON array of complete links and explicit expectations")
        command.add_argument("--idempotency-key", required=True)


def run(args, credential):
    from .drafts import DraftClient, DraftService, _failure
    from .workspace import Workspace
    actions = {"schema": "get_project_schema", "get": "get_project",
               "prepare": "prepare_project", "propose": "propose_project"}
    fields = ("project_id", "revision", "expected_revision", "idempotency_key")
    arguments = {k: getattr(args, k) for k in fields if hasattr(args, k)}
    client = None
    try:
        for field in ("devices", "links"):
            if hasattr(args, field):
                value = getattr(args, field)
                if len(value) > 64_000:
                    raise ValueError()
                arguments[field] = json.loads(value)
        workspace = Workspace(args.workspace)
        client = DraftClient(credential, args.server)
        return DraftService(workspace, client).call(actions[args.project_command], arguments)
    except (ValueError, OSError, RuntimeError, RecursionError):
        return _failure("invalid_arguments")
    finally:
        if client is not None:
            client.close()
