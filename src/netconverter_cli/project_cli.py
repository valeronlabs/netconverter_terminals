"""Noninteractive candidate project commands using the guided transport."""
import json

from .draft_cli import _revision


def add_parser(subparsers):
    project = subparsers.add_parser("project", help="prepare a candidate multi-device project; no project execution")
    commands = project.add_subparsers(dest="project_command", required=True)
    commands.add_parser("schema", help="print the project document schema the server accepts")
    get = commands.add_parser("get", help="show one project revision")
    get.add_argument("project_id", help="project id returned by project prepare")
    get.add_argument("--revision", type=_revision, required=True, help="project revision (a positive integer)")
    for name, text in (("prepare", "create a candidate project from prepared drafts and their links"),
                       ("propose", "record a new project revision (devices and links)")):
        command = commands.add_parser(name, help=text)
        if name == "propose":
            command.add_argument("project_id", help="project id returned by project prepare")
            command.add_argument("--expected-revision", type=_revision, required=True,
                                 help="the revision you are changing; refused if the project moved on")
        command.add_argument("--devices", required=True, help="JSON array of device_id, draft_id and revision references")
        command.add_argument("--links", required=True, help="JSON array of complete links and explicit expectations")
        command.add_argument("--idempotency-key", required=True,
                             help="any unique string; reuse it when retrying the same request")


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
