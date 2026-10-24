"""Opt-in client for the proposed guided-workflow contract version 1.

The server owns drafts, validation, and human approval. This module never
simulates those capabilities, stores credentials/receipts, or submits legacy
configuration jobs when the new contract is absent.
"""
from __future__ import annotations

import hashlib
import re
from urllib.parse import urlsplit

from .api import APIError, ExternalClient
from .draft_io import MAX_DOCUMENT_BYTES, secure_publish, secure_snapshot
from .workspace import Workspace, WorkspaceError

ACTIONS = ("prepare_draft", "get_required_decisions", "propose_changes", "validate_draft",
           "request_review", "execute_approved", "export_document")
RESOURCE_ACTIONS = ("read_context", "read_evidence", "read_catalog")
_ID = re.compile(r"[A-Za-z0-9_-]{1,80}\Z")
_HASH = re.compile(r"[a-f0-9]{64}\Z")
_KEY = re.compile(r"[A-Za-z0-9_-]{8,128}\Z")
_MESSAGES = {
    "unsupported_capability": "The server has not enabled this guided-workflow contract for this credential.",
    "invalid_arguments": "Supply valid explicit identifiers, revision, and supported arguments.",
    "input_unavailable": "The input could not be read securely within the workspace and size limit.",
    "artifact_invalid": "The document manifest or checksum did not match the requested draft revision.",
    "artifact_conflict": "The document could not be saved without replacing an existing file.",
    "invalid_response": "The server returned an invalid guided-workflow response.",
    "needs_input": "The draft requires additional decisions before this action.",
    "revision_conflict": "The draft changed; retrieve its current revision and reconcile before retrying.",
    "revalidation_required": "The selected draft revision requires current validation.",
    "approval_required": "This exact draft revision requires a current human-bound approval.",
    "access_denied": "This credential is not authorized for the requested operation.",
    "not_found": "The requested resource is unavailable to this credential.",
    "rate_limited": "The server is limiting requests; retry later with the same idempotency key.",
    "connection_failed": "The request could not be completed; retry writes with the same idempotency key.",
    "request_failed": "The server could not complete this guided-workflow request.",
}


def _object(properties, required=()):
    return {"type": "object", "properties": properties, "required": list(required), "additionalProperties": False}


ID_SCHEMA = {"type": "string", "pattern": "^[A-Za-z0-9_-]{1,80}$"}
DECISION_ID_SCHEMA = {"type": "string", "pattern": "^dec_[a-f0-9]{32}$"}
CHOICE_ID_SCHEMA = {"type": "string", "pattern": "^cho_[a-f0-9]{32}$"}
ENTITY_REF_SCHEMA = {"type": "string", "pattern": "^ent_[a-f0-9]{32}$"}
HASH_SCHEMA = {"type": "string", "pattern": "^[a-f0-9]{64}$"}
REV_SCHEMA = {"type": "integer", "minimum": 1}
COUNT_SCHEMA = {"type": "integer", "minimum": 0, "maximum": 1_000_000_000}
CHOICE_SCHEMA = _object({"choice_id": CHOICE_ID_SCHEMA, "requires_input": {"type": "boolean"}}, ("choice_id",))
DECISION_SCHEMA = _object({
    "decision_id": DECISION_ID_SCHEMA, "entity_ref": ENTITY_REF_SCHEMA, "required": {"type": "boolean"},
    "choices": {"type": "array", "maxItems": 100, "items": CHOICE_SCHEMA},
}, ("decision_id",))
DATA_PROPERTIES = {
    "draft_kind": {"const": "migration"},
    "source_vendor": {"const": "cisco_asa"}, "target_vendor": {"const": "palo_alto_set"},
    "migration_pairs": {"type": "array", "maxItems": 1, "items": _object({
        "source_vendor": {"const": "cisco_asa"}, "target_vendor": {"const": "palo_alto_set"},
    }, ("source_vendor", "target_vendor"))},
    **{name: ID_SCHEMA for name in ("draft_id", "job_id", "validation_id", "review_id", "approval_ref", "view_id", "catalog_version", "entry_id")},
    **{name: HASH_SCHEMA for name in ("content_sha256", "source_sha256", "document_sha256", "validation_sha256", "sha256")},
    **{name: REV_SCHEMA for name in ("revision", "digest_revision")},
    "bytes": COUNT_SCHEMA,
    "path": {"type": "string", "maxLength": 4096},
    "review_url": {"type": "string", "maxLength": 2048},
    "enabled": {"type": "boolean"}, "contract_version": {"const": "1"},
    "approval_mode": {"const": "human_bound"}, "agent_restricted": {"const": True},
    "operations": {"type": "array", "maxItems": len(ACTIONS + RESOURCE_ACTIONS), "uniqueItems": True,
                   "items": {"enum": list(ACTIONS + RESOURCE_ACTIONS)}},
    "status": {"enum": ["prepared", "needs_input", "ready", "pending_review", "approved", "submitted", "queued", "running", "complete", "failed", "stale"]},
    "validation_status": {"enum": ["passed", "failed", "inconclusive", "not_evaluated", "needs_review"]},
    "verdict": {"enum": ["PASS", "FAIL", "INCONCLUSIVE", "NOT_EVALUATED", "NEEDS_REVIEW"]},
    "coverage": _object({key: COUNT_SCHEMA for key in ("parsed", "ignored", "unparsed", "unaccounted")}),
    "required_decisions": {"type": "array", "maxItems": 200, "items": DECISION_SCHEMA},
    "next_actions": {"type": "array", "maxItems": len(ACTIONS), "uniqueItems": True, "items": {"enum": list(ACTIONS)}},
    "view_mode": {"enum": ["strict", "default", "full_addresses"]},
    "view_level_requested": {"enum": ["none", "masked", "selected", "full", "strict", "default", "full_addresses"]},
    "view_clamped": {"type": "boolean"},
    "view_enforced_by": {"const": "server"},
}
OUTPUT_SCHEMA = {
    "type": "object",
    "oneOf": [
        _object({"schema_version": {"const": "1"}, "ok": {"const": True}, "data": _object(DATA_PROPERTIES)}, ("schema_version", "ok", "data")),
        _object({"schema_version": {"const": "1"}, "ok": {"const": False}, "error": _object({
            "code": {"enum": list(_MESSAGES)}, "message": {"type": "string", "maxLength": 200},
            "expected_revision": REV_SCHEMA, "current_revision": REV_SCHEMA,
        }, ("code", "message"))}, ("schema_version", "ok", "error")),
    ]
}


def _success(data):
    return {"schema_version": "1", "ok": True, "data": data}


def _failure(code, **fields):
    return {"schema_version": "1", "ok": False, "error": {"code": code, "message": _MESSAGES[code], **fields}}


class DraftError(ValueError):
    def __init__(self, code):
        self.code = code


def _identifier(value):
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise DraftError("invalid_arguments")
    return value


def _revision(value):
    if type(value) is not int or value <= 0:
        raise DraftError("invalid_arguments")
    return value


def _digest(value):
    return isinstance(value, str) and bool(_HASH.fullmatch(value))


def _project(value, schema):
    """Recursively allow only typed contract fields; never copy arbitrary text."""
    if "const" in schema:
        if type(value) is type(schema["const"]) and value == schema["const"]:
            return value
        raise DraftError("invalid_response")
    if "enum" in schema:
        if isinstance(value, str) and value in schema["enum"]:
            return value
        raise DraftError("invalid_response")
    kind = schema.get("type")
    if kind == "object":
        if not isinstance(value, dict):
            raise DraftError("invalid_response")
        result = {}
        for key, child in schema["properties"].items():
            if key in value:
                result[key] = _project(value[key], child)
        if not all(key in result for key in schema["required"]):
            raise DraftError("invalid_response")
        return result
    if kind == "array":
        if not isinstance(value, list) or len(value) > schema["maxItems"]:
            raise DraftError("invalid_response")
        result = []
        for item in value:
            projected = _project(item, schema["items"])
            if schema.get("uniqueItems") and projected in result:
                raise DraftError("invalid_response")
            result.append(projected)
        return result
    if kind == "integer":
        if type(value) is int and schema.get("minimum", 0) <= value <= schema.get("maximum", 2**53 - 1):
            return value
        raise DraftError("invalid_response")
    if kind == "boolean":
        if type(value) is bool:
            return value
        raise DraftError("invalid_response")
    if kind == "string":
        if not isinstance(value, str) or len(value) > schema.get("maxLength", 128):
            raise DraftError("invalid_response")
        if "pattern" in schema and not re.fullmatch(schema["pattern"], value):
            raise DraftError("invalid_response")
        return value
    raise DraftError("invalid_response")


class DraftClient(ExternalClient):
    """Exact new routes only; inherited transport preserves credential handling."""
    _ALLOWED = re.compile(
        r"(?:capabilities|jobs|drafts|drafts/[A-Za-z0-9_-]{1,80}(?:/document|/proposals|/validate|/review-requests|/approval-status|/context)?"
        r"|jobs/[A-Za-z0-9_-]{1,80}/evidence-digest|catalog/[A-Za-z0-9_-]{1,80}/entries/[A-Za-z0-9_-]{1,80})\Z"
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.http.headers["X-NetConverter-View"] = "strict"

    def _send(self, method, path, idempotency_key=None, **kwargs):
        read_path = (path == "capabilities" or re.fullmatch(r"drafts/[A-Za-z0-9_-]{1,80}(?:/document|/approval-status|/context)?", path)
                     or re.fullmatch(r"jobs/[A-Za-z0-9_-]{1,80}/evidence-digest", path)
                     or re.fullmatch(r"catalog/[A-Za-z0-9_-]{1,80}/entries/[A-Za-z0-9_-]{1,80}", path))
        write_path = path in {"drafts", "jobs"} or re.fullmatch(r"drafts/[A-Za-z0-9_-]{1,80}/(?:proposals|validate|review-requests)", path)
        if not ((method == "GET" and read_path) or (method == "POST" and write_path)):
            raise ValueError("Unsupported draft method or path")
        return super()._send(method, path, idempotency_key, **kwargs)

    def request(self, method, path, *, idempotency_key=None, **kwargs):
        response, request_id = self._send(method, path, idempotency_key, **kwargs)
        if len(response.content) > 2_000_000:
            raise APIError(response.status_code, "invalid_response", request_id)
        if not 200 <= response.status_code < 300:
            raise self._error(response, request_id)
        try:
            body = response.json()
        except ValueError:
            raise APIError(response.status_code, "invalid_response", request_id) from None
        if not isinstance(body, dict) or body.get("success") is not True or not isinstance(body.get("data"), dict):
            raise APIError(response.status_code, "invalid_response", request_id)
        return body["data"]


class DraftService:
    def __init__(self, workspace: Workspace, client: DraftClient):
        self.workspace, self.client = workspace, client

    def _capabilities(self):
        data = self.client.capabilities()
        guided = data.get("guided_workflows") if isinstance(data, dict) else None
        if (not isinstance(guided, dict) or guided.get("contract_version") != "1" or
                guided.get("enabled") is not True or guided.get("approval_mode") != "human_bound" or
                guided.get("view_mode") != "strict" or guided.get("view_enforced_by") != "server" or
                guided.get("agent_restricted") is not True or not isinstance(guided.get("operations"), list) or
                any(not isinstance(item, str) for item in guided["operations"]) or
                not isinstance(guided.get("migration_pairs"), list) or
                not any(isinstance(pair, dict) and pair.get("source_vendor") == "cisco_asa" and
                        pair.get("target_vendor") == "palo_alto_set" for pair in guided["migration_pairs"])):
            raise DraftError("unsupported_capability")
        return {"enabled": True, "contract_version": "1", "approval_mode": "human_bound", "agent_restricted": True,
                "view_mode": "strict", "view_enforced_by": "server",
                "migration_pairs": [{"source_vendor": "cisco_asa", "target_vendor": "palo_alto_set"}],
                "operations": [action for action in ACTIONS + RESOURCE_ACTIONS if action in guided["operations"]]}

    def capabilities(self):
        try:
            return _success(self._capabilities())
        except APIError as exc:
            return self._api_error(exc)
        except DraftError as exc:
            return _failure(exc.code)
        except (ValueError, KeyError, TypeError):
            return _failure("invalid_response")

    @staticmethod
    def _api_error(exc):
        code = exc.code if exc.code in _MESSAGES else {
            401: "access_denied", 403: "access_denied", 404: "not_found", 409: "revision_conflict",
            429: "rate_limited", 0: "connection_failed",
        }.get(exc.status, "request_failed")
        fields = {}
        if code == "revision_conflict" and isinstance(exc.detail, dict):
            for name in ("expected_revision", "current_revision"):
                if type(exc.detail.get(name)) is int and exc.detail[name] > 0:
                    fields[name] = exc.detail[name]
        return _failure(code, **fields)

    def call(self, action: str, arguments: dict):
        try:
            if action not in ACTIONS + RESOURCE_ACTIONS or not isinstance(arguments, dict):
                raise DraftError("invalid_arguments")
            capabilities = self._capabilities()
            if action not in capabilities["operations"]:
                raise DraftError("unsupported_capability")
            return _success(self._run(action, arguments))
        except APIError as exc:
            return self._api_error(exc)
        except DraftError as exc:
            return _failure(exc.code)
        except WorkspaceError:
            return _failure("input_unavailable")
        except (ValueError, KeyError, TypeError, UnicodeError):
            return _failure("invalid_response")

    @staticmethod
    def _arguments(arguments, required, optional=()):
        if not set(required).issubset(arguments) or not set(arguments).issubset(set(required) | set(optional)):
            raise DraftError("invalid_arguments")

    @staticmethod
    def _idempotency(arguments):
        key = arguments.get("idempotency_key")
        if not isinstance(key, str) or not _KEY.fullmatch(key):
            raise DraftError("invalid_arguments")
        return key

    @staticmethod
    def _project_data(data):
        if not isinstance(data, dict):
            raise DraftError("invalid_response")
        # Local path and review URL have separate validation and can never be
        # accepted simply because upstream labelled them as such.
        properties = {k: v for k, v in DATA_PROPERTIES.items() if k not in {"path", "review_url"}}
        return _project(data, _object(properties))

    def _response(self, data, draft_id=None, revision=None, *, changed=False):
        if not isinstance(data, dict):
            raise DraftError("invalid_response")
        if draft_id is not None and data.get("draft_id") != draft_id:
            raise DraftError("invalid_response")
        if revision is not None:
            actual = data.get("revision")
            if type(actual) is not int or (actual != revision if not changed else actual <= revision):
                raise DraftError("invalid_response")
        return self._project_data(data)

    @staticmethod
    def _migration(data):
        if (data.get("draft_kind") != "migration" or data.get("source_vendor") != "cisco_asa" or
                data.get("target_vendor") != "palo_alto_set"):
            raise DraftError("unsupported_capability")

    def _current_draft(self, draft_id, revision):
        data = self.client.request("GET", f"drafts/{draft_id}", params={"revision": revision})
        self._migration(data)
        projected = self._response(data, draft_id, revision)
        return projected

    def _run(self, action, args):
        if action == "prepare_draft":
            self._arguments(args, ("path", "idempotency_key"), ("source_vendor", "target_vendor", "workflow"))
            key = self._idempotency(args)
            source, target, workflow = args.get("source_vendor", "cisco_asa"), args.get("target_vendor", "palo_alto_set"), args.get("workflow", "studio")
            if source != "cisco_asa" or target != "palo_alto_set" or workflow not in {"studio", "quick"}:
                raise DraftError("unsupported_capability")
            _, content, sha = secure_snapshot(self.workspace, args["path"])
            data = self.client.request("POST", "drafts", idempotency_key=key,
                json={"draft_kind": "migration", "source_vendor": source, "target_vendor": target, "workflow": workflow,
                      "source_config": content.decode("utf-8"), "source_sha256": sha})
            projected = self._response(data)
            _identifier(projected.get("draft_id"))
            _revision(projected.get("revision"))
            self._migration(projected)
            if projected.get("source_sha256") != sha:
                raise DraftError("invalid_response")
            return projected
        if action in RESOURCE_ACTIONS:
            return self._read_resource(action, args)
        required = ["draft_id", "revision"]
        if action not in {"get_required_decisions", "export_document"}:
            required.append("idempotency_key")
        if action == "execute_approved":
            required.append("approval_ref")
        self._arguments(args, required, ("changes", "yaml_path") if action == "propose_changes" else ())
        draft_id, revision = _identifier(args["draft_id"]), _revision(args["revision"])
        route = f"drafts/{draft_id}"
        if action == "get_required_decisions":
            return self._current_draft(draft_id, revision)
        if action == "export_document":
            self._current_draft(draft_id, revision)
            return self._export_document(draft_id, revision)
        key = self._idempotency(args)
        body = {"expected_revision": revision}
        if action == "propose_changes":
            if ("changes" in args) == ("yaml_path" in args):
                raise DraftError("invalid_arguments")
            if "yaml_path" in args:
                self._current_draft(draft_id, revision)
                _, content, sha = secure_snapshot(self.workspace, args["yaml_path"], MAX_DOCUMENT_BYTES)
                body.update(document=content.decode("utf-8"), document_sha256=sha)
            else:
                changes = args["changes"]
                if not isinstance(changes, list) or not 1 <= len(changes) <= 100:
                    raise DraftError("invalid_arguments")
                for change in changes:
                    if not isinstance(change, dict):
                        raise DraftError("invalid_arguments")
                    self._arguments(change, ("decision_id", "choice_id"), ("entity_ref",))
                    for field, schema in (("decision_id", DECISION_ID_SCHEMA), ("choice_id", CHOICE_ID_SCHEMA), ("entity_ref", ENTITY_REF_SCHEMA)):
                        if field in change and (not isinstance(change[field], str) or not re.fullmatch(schema["pattern"], change[field])):
                            raise DraftError("invalid_arguments")
                body["changes"] = changes
                self._current_draft(draft_id, revision)
            return self._response(self.client.request("POST", route + "/proposals", idempotency_key=key, json=body), draft_id, revision, changed=True)
        if action == "execute_approved":
            approval_ref = _identifier(args["approval_ref"])
            current = self._current_draft(draft_id, revision)
            approval = self.client.request("GET", route + "/approval-status", params={"revision": revision})
            if (not isinstance(approval, dict) or approval.get("draft_id") != draft_id or
                    type(approval.get("revision")) is not int or approval.get("revision") != revision or
                    approval.get("approval_ref") != approval_ref or approval.get("status") != "approved" or
                    approval.get("human_bound") is not True or approval.get("validation_status") != "passed" or
                    not _digest(approval.get("content_sha256")) or
                    approval.get("content_sha256") != current.get("content_sha256") or
                    approval.get("content_sha256") != approval.get("validated_content_sha256")):
                raise DraftError("approval_required")
            data = self.client.request("POST", "jobs", idempotency_key=key,
                json={"approved_draft_id": draft_id, "draft_revision": revision, "approval_ref": approval_ref})
            projected = self._project_data(data)
            _identifier(projected.get("job_id"))
            return projected
        suffix = "/validate" if action == "validate_draft" else "/review-requests"
        self._current_draft(draft_id, revision)
        data = self.client.request("POST", route + suffix, idempotency_key=key, json=body)
        projected = self._response(data, draft_id, revision)
        if action == "request_review":
            review_id = projected.get("review_id")
            _identifier(review_id)
            expected = str(self.client.http.base_url) + route + "/reviews/" + review_id
            if data.get("review_url") == expected and not urlsplit(expected).query and not urlsplit(expected).fragment:
                projected["review_url"] = expected
            else:
                raise DraftError("invalid_response")
        return projected

    def _export_document(self, draft_id, revision):
        data = self.client.request("GET", f"drafts/{draft_id}/document", params={"revision": revision})
        if (not isinstance(data, dict) or data.get("draft_id") != draft_id or type(data.get("revision")) is not int or
                data.get("revision") != revision or not isinstance(data.get("document"), str) or not _digest(data.get("sha256"))):
            raise DraftError("artifact_invalid")
        content = data["document"].encode("utf-8")
        if not 0 < len(content) <= MAX_DOCUMENT_BYTES or b"\x00" in content or hashlib.sha256(content).hexdigest() != data["sha256"]:
            raise DraftError("artifact_invalid")
        try:
            path = secure_publish(self.workspace, draft_id, revision, content, data["sha256"])
        except (WorkspaceError, OSError):
            raise DraftError("artifact_conflict") from None
        return {"draft_id": draft_id, "revision": revision, "path": str(path), "sha256": data["sha256"], "bytes": len(content)}

    def _read_resource(self, action, args):
        if action == "read_context":
            self._arguments(args, ("draft_id", "revision", "view_id"))
            draft_id, revision, view_id = _identifier(args["draft_id"]), _revision(args["revision"]), _identifier(args["view_id"])
            data = self.client.request("GET", f"drafts/{draft_id}/context", params={"revision": revision, "view_id": view_id})
            result = self._response(data, draft_id, revision)
            self._migration(result)
            if result.get("view_id") != view_id:
                raise DraftError("invalid_response")
            return result
        if action == "read_evidence":
            self._arguments(args, ("job_id", "digest_revision"))
            job_id, revision = _identifier(args["job_id"]), _revision(args["digest_revision"])
            data = self.client.request("GET", f"jobs/{job_id}/evidence-digest", params={"digest_revision": revision})
            result = self._project_data(data)
            if result.get("job_id") != job_id or result.get("digest_revision") != revision:
                raise DraftError("invalid_response")
            return result
        self._arguments(args, ("catalog_version", "entry_id"))
        version, entry = _identifier(args["catalog_version"]), _identifier(args["entry_id"])
        result = self._project_data(self.client.request("GET", f"catalog/{version}/entries/{entry}"))
        if result.get("catalog_version") != version or result.get("entry_id") != entry:
            raise DraftError("invalid_response")
        return result
