"""Candidate project adapters. No configuration bytes or approval authority."""
import hashlib
import json
import re
from importlib.resources import files

CONTRACT = json.loads(files("netconverter_cli").joinpath("guided_projects.json").read_text())
OPERATIONS = ("get_project_schema", "prepare_project", "get_project", "propose_project")
PROJECT_ID = CONTRACT["response"]["properties"]["project_id"]


def validate_request(value, schema):
    from .drafts import DraftError, _project
    try:
        if _project(value, schema) != value:
            raise DraftError("invalid_arguments")
        if schema.get("type") == "object":
            for key, child in value.items():
                validate_request(child, schema["properties"][key])
        if schema.get("type") == "array":
            if len(value) < schema.get("minItems", 0):
                raise DraftError("invalid_arguments")
            for child in value:
                validate_request(child, schema["items"])
    except (KeyError, TypeError, ValueError):
        raise DraftError("invalid_arguments") from None


def run(service, action, args):
    from .drafts import DraftError, _project, _revision
    if action == "get_project_schema":
        service._arguments(args, ())
        if service.client.request("GET", "guided/project-schema") != CONTRACT:
            raise DraftError("unsupported_capability")
        return {"project_schema": CONTRACT}
    if action == "get_project":
        service._arguments(args, ("project_id", "revision"))
    elif action == "prepare_project":
        service._arguments(args, ("devices", "links", "idempotency_key"))
    else:
        service._arguments(args, ("project_id", "expected_revision", "devices", "links", "idempotency_key"))
    project = args.get("project_id")
    if action != "prepare_project" and (not isinstance(project, str) or not re.fullmatch(PROJECT_ID["pattern"], project)):
        raise DraftError("invalid_arguments")
    revision = _revision(args["revision"]) if action == "get_project" else None
    if action == "get_project":
        data = service.client.request("GET", f"guided/projects/{project}", params={"revision": revision})
    else:
        key = service._idempotency(args)
        body = {k: args[k] for k in ("devices", "links", "expected_revision") if k in args}
        validate_request(body, CONTRACT["create" if action == "prepare_project" else "propose"])
        # Exact schema matching precedes every mutation; never accept a remotely
        # expanded arbitrary-field schema or cache qualification across calls.
        run(service, "get_project_schema", {})
        path = "guided/projects" if project is None else f"guided/projects/{project}/proposals"
        data = service.client.request("POST", path, idempotency_key=key, json=body)
        revision = 1 if project is None else args["expected_revision"] + 1
    result = _project(data, CONTRACT["response"])
    if result["revision"] != revision or (project is not None and result["project_id"] != project):
        raise DraftError("invalid_response")
    # The frozen project snapshot has its own digest, separate from evidence.
    snapshot = result["snapshot"]
    if action != "get_project":
        references = [{key: d[key] for key in ("device_id", "draft_id", "revision")}
                      for d in snapshot["devices"]]
        if references != body["devices"] or snapshot["links"] != body["links"]:
            raise DraftError("invalid_response")
    digest = hashlib.sha256(json.dumps(snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                                       allow_nan=False).encode()).hexdigest()
    evidence = result["cross_device_evidence"]
    if (digest != result["content_sha256"] or evidence["project_content_sha256"] != digest
            or result["current_revision"] < result["revision"]
            or result["validation"]["cross_device_consistency"] != evidence["status"]
            or bool(result["stale_devices"]) != (result["state"] == "stale")):
        raise DraftError("invalid_response")
    device_ids = {d["device_id"] for d in snapshot["devices"]}
    if not snapshot["devices"] or not set(result["stale_devices"]) <= device_ids:
        raise DraftError("invalid_response")
    if any(row["link_index"] >= len(snapshot["links"]) for row in evidence["checks"] + evidence["design_requirements"]):
        raise DraftError("invalid_response")
    return {"project": result}
