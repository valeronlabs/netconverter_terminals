"""Synthetic contract tests; they do not establish live server support."""
import hashlib
import json

import httpx
import pytest

from netconverter_cli.drafts import ACTIONS, RESOURCE_ACTIONS, DraftClient, DraftService, OUTPUT_SCHEMA
from netconverter_cli.workspace import Workspace

CANARY = "PRIVATE_config_comment_or_secret_canary"
SHA = hashlib.sha256(b"source").hexdigest()
KEY = "request_12345678"


def capabilities(**changes):
    guided = {"contract_version": "1", "enabled": True, "approval_mode": "human_bound", "agent_restricted": True, "view_mode": "strict", "view_enforced_by": "server",
              "operations": list(ACTIONS + RESOURCE_ACTIONS),
              "migration_pairs": [{"source_vendor": "cisco_asa", "target_vendor": "palo_alto_set"}]}
    guided.update(changes)
    return {"guided_workflows": guided}


def success(data):
    return httpx.Response(200, json={"success": True, "data": data})


def service(tmp_path, handler, caps=None, metadata=None):
    seen = []
    def serve(request):
        seen.append(request)
        if request.url.path.endswith("/capabilities"):
            return success(capabilities() if caps is None else caps)
        if request.method == "GET" and request.url.path.endswith("/drafts/draft_1"):
            return success(metadata if metadata is not None else draft(revision=int(request.url.params["revision"])))
        return handler(request)
    client = DraftClient("test_only", transport=httpx.MockTransport(serve))
    return DraftService(Workspace(tmp_path), client), seen


def draft(**changes):
    data = {"draft_id": "draft_1", "revision": 1, "content_sha256": SHA, "draft_kind": "migration",
            "source_vendor": "cisco_asa", "target_vendor": "palo_alto_set"}
    data.update(changes)
    return data


def args(**changes):
    result = {"draft_id": "draft_1", "revision": 1, "idempotency_key": KEY}
    result.update(changes)
    return result


@pytest.mark.parametrize("caps", [{}, {"guided_workflows": {}}, capabilities(enabled=False), capabilities(agent_restricted=False),
                                   capabilities(approval_mode="model"), capabilities(contract_version="2"), capabilities(operations="prepare_draft")])
def test_disabled_capability_precedes_file_access_and_upload(tmp_path, monkeypatch, caps):
    def fail_read(*a, **k):
        pytest.fail("No local read when capability is absent")
    monkeypatch.setattr("netconverter_cli.drafts.secure_snapshot", fail_read)
    svc, seen = service(tmp_path, lambda req: pytest.fail("No upload"), caps)
    result = svc.call("prepare_draft", {"path": "secret.cfg", "idempotency_key": KEY})
    assert result["error"]["code"] == "unsupported_capability"
    assert len(seen) == 1


def test_capability_checked_fresh_and_scoped_per_operation(tmp_path):
    svc, seen = service(tmp_path, lambda req: success(draft()), capabilities(operations=["get_required_decisions"]))
    assert svc.call("get_required_decisions", {"draft_id": "draft_1", "revision": 1})["ok"]
    assert svc.call("validate_draft", args())["error"]["code"] == "unsupported_capability"
    assert [req.url.path.split("/")[-1] for req in seen] == ["capabilities", "draft_1", "capabilities"]


def test_source_direct_transport_never_projected(tmp_path):
    (tmp_path / "source.cfg").write_text(CANARY)
    captured = []
    def handle(request):
        captured.append(json.loads(request.content))
        assert request.headers["Idempotency-Key"] == KEY
        return success(draft(source_sha256=hashlib.sha256(CANARY.encode()).hexdigest(), source_config=CANARY, description=CANARY, path=CANARY, detail=CANARY,
                             required_decisions=[{"decision_id": "dec_" + "1" * 32, "name": CANARY, "required": True,
                                                  "choices": [{"choice_id": "cho_" + "1" * 32, "label": CANARY}]}]))
    svc, _ = service(tmp_path, handle)
    result = svc.call("prepare_draft", {"path": "source.cfg", "idempotency_key": KEY})
    assert result["ok"]
    assert captured[0]["source_config"] == CANARY
    assert captured[0]["source_sha256"] == hashlib.sha256(CANARY.encode()).hexdigest()
    assert CANARY not in json.dumps(result)
    assert result["data"]["required_decisions"] == [{"decision_id": "dec_" + "1" * 32, "required": True, "choices": [{"choice_id": "cho_" + "1" * 32}]}]


@pytest.mark.parametrize("changes", [{"revision": True}, {"revision": 0}, {"revision": "1"}, {"draft_id": "../draft_1"}, {"idempotency_key": ""}])
def test_invalid_explicit_handles_never_mutate(tmp_path, changes):
    svc, seen = service(tmp_path, lambda req: pytest.fail("No mutation"))
    assert svc.call("validate_draft", args(**changes))["error"]["code"] == "invalid_arguments"
    assert len(seen) == 1


def test_exact_revision_and_key_in_mutation(tmp_path):
    def handle(request):
        assert request.url.path.endswith("/validate")
        assert json.loads(request.content) == {"expected_revision": 7}
        assert request.headers["Idempotency-Key"] == KEY
        return success(draft(revision=7, validation_status="needs_review"))
    svc, _ = service(tmp_path, handle)
    assert svc.call("validate_draft", args(revision=7))["ok"]


def test_conflict_not_retried_and_error_fields_sanitized(tmp_path):
    def handle(request):
        return httpx.Response(409, json={"success": False, "error": {"code": "revision_conflict", "message": CANARY,
                "detail": {"expected_revision": 1, "current_revision": 2, "document": CANARY}}})
    svc, seen = service(tmp_path, handle)
    result = svc.call("validate_draft", args())
    assert result["error"]["code"] == "revision_conflict"
    assert result["error"]["current_revision"] == 2
    assert CANARY not in json.dumps(result)
    assert len(seen) == 3


def test_unknown_error_code_and_detail_never_echo(tmp_path):
    svc, _ = service(tmp_path, lambda req: httpx.Response(500, json={"error": {"code": CANARY, "message": CANARY}, "detail": CANARY}))
    result = svc.call("validate_draft", args())
    assert result["error"]["code"] == "request_failed"
    assert CANARY not in json.dumps(result)


def test_yaml_upload_direct_and_strict_change_contract(tmp_path):
    content = f"decisions:\n  name: {CANARY}\n"
    (tmp_path / "decisions.yaml").write_text(content)
    def handle(request):
        body = json.loads(request.content)
        assert body == {"expected_revision": 1, "document": content, "document_sha256": hashlib.sha256(content.encode()).hexdigest()}
        return success(draft(revision=2, document=content))
    svc, seen = service(tmp_path, handle)
    result = svc.call("propose_changes", args(yaml_path="decisions.yaml"))
    assert result["ok"] and result["data"]["revision"] == 2
    assert CANARY not in json.dumps(result)
    for change in [{"decision_id": "dec_" + "1" * 32, "choice_id": "cho_" + "1" * 32, "content": CANARY}, {"op": "replace", "value": CANARY}]:
        assert svc.call("propose_changes", args(changes=[change]))["error"]["code"] == "invalid_arguments"
    assert len(seen) == 5  # proposal + metadata read + three capability checks


def approved(**changes):
    result = draft(approval_ref="approval_1", status="approved", human_bound=True,
                   validation_status="not_evaluated", validated_content_sha256=SHA,
                   submission_readiness="ready_for_submission", approval_scope="migration_submission")
    result.update(changes)
    return result


@pytest.mark.parametrize("changes", [{"status": "pending_review"}, {"human_bound": False}, {"revision": 2}, {"revision": True},
                                     {"approval_ref": "wrong"}, {"draft_id": "other"}, {"validated_content_sha256": "0" * 64},
                                     {"submission_readiness": "blocked"}, {"submission_readiness": None},
                                     {"approval_scope": "device_deployment"}, {"approval_scope": None},
                                     {"human_bound": "true"}, {"human_bound": 1},
                                     {"validation_status": "passed", "submission_readiness": "blocked"}])
def test_false_stale_or_other_approval_blocks_execution(tmp_path, changes):
    def handle(request):
        assert request.method == "GET"
        assert request.url.path.endswith("/approval-status")
        return success(approved(**changes))
    svc, seen = service(tmp_path, handle)
    result = svc.call("execute_approved", args(approval_ref="approval_1"))
    assert result["error"]["code"] == "approval_required"
    assert not any(req.method == "POST" for req in seen)


def test_execution_uses_current_server_approval_and_no_raw_config(tmp_path):
    def handle(request):
        if request.url.path.endswith("/approval-status"):
            assert request.url.params["revision"] == "1"
            return success(approved())
        assert request.url.path.endswith("/guided/jobs")
        assert json.loads(request.content) == {"approved_draft_id": "draft_1", "draft_revision": 1, "approval_ref": "approval_1"}
        assert request.headers["Idempotency-Key"] == KEY
        return success({"job_id": "job_1", "status": "queued", "source_config": CANARY})
    svc, seen = service(tmp_path, handle)
    result = svc.call("execute_approved", args(approval_ref="approval_1"))
    assert result == {"schema_version": "1", "ok": True, "data": {"job_id": "job_1", "status": "queued"}}
    assert len(seen) == 4


@pytest.mark.parametrize("status", ["not_evaluated", "needs_review"])
def test_submission_approval_does_not_require_an_output_pass(tmp_path, status):
    def handle(request):
        if request.method == "GET":
            return success(approved(validation_status=status))
        assert request.url.path == "/external/v1/guided/jobs"
        return success({"job_id": "job_1", "status": "queued"})
    svc, seen = service(tmp_path, handle)
    assert svc.call("execute_approved", args(approval_ref="approval_1"))["ok"]
    assert len([request for request in seen if request.method == "POST"]) == 1


def test_output_pass_without_independent_submission_receipt_cannot_execute(tmp_path):
    svc, seen = service(tmp_path, lambda request: success(draft(validation_status="passed")))
    result = svc.call("execute_approved", args(approval_ref="approval_1"))
    assert result["error"]["code"] == "approval_required"
    assert not any(request.method == "POST" for request in seen)


@pytest.mark.parametrize("new_validation_status", ["not_evaluated", "needs_review", "failed", "inconclusive"])
def test_consumed_receipt_recovers_lost_response_after_revalidation(tmp_path, new_validation_status):
    state = {"consumed": False, "jobs": 0}
    payloads = []
    current = draft()
    def handle(request):
        if request.url.path.endswith("/approval-status"):
            if state["consumed"]:
                # New validation may block another conversion. The consumed
                # receipt still references the earlier immutable job/content.
                return success(approved(status="consumed", validation_status=new_validation_status))
            return success(approved())
        assert request.url.path == "/external/v1/guided/jobs"
        payloads.append((request.headers["Idempotency-Key"], json.loads(request.content)))
        if not state["consumed"]:
            state.update(consumed=True, jobs=1)
            current.update(revision=2, content_sha256="0" * 64,
                           validation_status=new_validation_status, submission_readiness="blocked")
            raise httpx.ReadTimeout("Synthetic response loss after committed submission", request=request)
        return success({"job_id": "job_original", "status": "queued"})
    svc, seen = service(tmp_path, handle, metadata=current)
    arguments = args(approval_ref="approval_1")
    assert svc.call("execute_approved", arguments)["error"]["code"] == "connection_failed"
    recovered = svc.call("execute_approved", arguments)
    assert recovered["ok"] and recovered["data"]["job_id"] == "job_original"
    assert state["jobs"] == 1 and payloads[0] == payloads[1]
    assert len([request for request in seen if request.url.path.endswith("/drafts/draft_1")]) == 1
    assert CANARY not in json.dumps(recovered)


@pytest.mark.parametrize("changes", [{"human_bound": False}, {"approval_scope": "device_deployment"},
    {"approval_ref": "another"}, {"revision": 2}, {"content_sha256": "0" * 64},
    {"validated_content_sha256": "0" * 64}])
def test_consumed_recovery_retains_identity_and_content_guards(tmp_path, changes):
    svc, seen = service(tmp_path, lambda request: success(approved(status="consumed", **changes)))
    assert svc.call("execute_approved", args(approval_ref="approval_1"))["error"]["code"] == "approval_required"
    assert not any(request.method == "POST" for request in seen)


def test_consumed_recovery_rechecks_capability_and_server_authorization(tmp_path):
    capability = capabilities()
    def denied(request):
        assert request.url.path.endswith("/approval-status")
        return httpx.Response(403, json={"error": {"code": "access_denied", "message": CANARY}})
    svc, seen = service(tmp_path, denied, caps=capability)
    result = svc.call("execute_approved", args(approval_ref="approval_1"))
    assert not result["ok"] and CANARY not in json.dumps(result)
    assert not any(request.method == "POST" for request in seen)
    capability["guided_workflows"]["operations"].remove("execute_approved")
    before = len(seen)
    assert svc.call("execute_approved", args(approval_ref="approval_1"))["error"]["code"] == "unsupported_capability"
    assert len(seen) == before + 1


def test_document_manifest_hash_identity_and_no_clobber(tmp_path):
    document = f"source: {CANARY}\n"
    manifest = draft(document=document, sha256=hashlib.sha256(document.encode()).hexdigest(), filename="../../overwrite")
    svc, _ = service(tmp_path, lambda req: success(manifest))
    request = {"draft_id": "draft_1", "revision": 1}
    result = svc.call("export_document", request)
    assert result["ok"]
    assert CANARY not in json.dumps(result)
    path = tmp_path / "draft_1.revision-1.yaml"
    assert path.read_text() == document
    assert svc.call("export_document", request)["ok"]
    path.write_text("engineer edits")
    assert svc.call("export_document", request)["error"]["code"] == "artifact_conflict"
    assert path.read_text() == "engineer edits"
    manifest["revision"] = 2
    assert svc.call("export_document", request)["error"]["code"] == "artifact_invalid"
    manifest["revision"], manifest["sha256"] = 1, "0" * 64
    assert svc.call("export_document", request)["error"]["code"] == "artifact_invalid"


def test_request_review_url_is_same_origin_exact_resource(tmp_path):
    body = draft(review_id="review_1", review_url="https://api.netconverter.ai/external/v1/drafts/draft_1/reviews/review_1")
    svc, _ = service(tmp_path, lambda req: success(body))
    assert svc.call("request_review", args())["ok"]
    for value in ["https://evil.example/review", body["review_url"] + "?token=" + CANARY, body["review_url"] + "#" + CANARY]:
        body["review_url"] = value
        result = svc.call("request_review", args())
        assert result["error"]["code"] == "invalid_response"
        assert CANARY not in json.dumps(result)


def test_resources_project_private_fields_and_match_request(tmp_path):
    data = draft(view_id="view_1", comments=CANARY, full_document=CANARY)
    svc, _ = service(tmp_path, lambda req: success(data))
    result = svc.call("read_context", {"draft_id": "draft_1", "revision": 1, "view_id": "view_1"})
    assert result["ok"] and CANARY not in json.dumps(result)
    data["view_id"] = "view_2"
    assert svc.call("read_context", {"draft_id": "draft_1", "revision": 1, "view_id": "view_1"})["error"]["code"] == "invalid_response"


def test_draft_transport_rejects_legacy_routes_and_methods(tmp_path):
    client = DraftClient("test_only", transport=httpx.MockTransport(lambda req: pytest.fail("No network")))
    for method, route in [("POST", "quick/jobs"), ("POST", "jobs"), ("GET", "jobs/job_1"),
                          ("GET", "jobs/job_1/artifacts"), ("GET", "me"),
                          ("DELETE", "drafts/draft_1"), ("PUT", "drafts/draft_1/document"), ("GET", "https://evil.example")]:
        with pytest.raises(ValueError):
            client.request(method, route)


def test_no_redirects_and_same_key_on_auth_refresh(tmp_path):
    class Credential:
        def __init__(self): self.refreshed = False
        def token(self): return "new" if self.refreshed else "old"
        def refresh(self): self.refreshed = True; return True
    seen = []
    def handle(request):
        seen.append(request)
        if request.headers["Authorization"] == "Bearer old":
            return httpx.Response(401)
        return success(draft())
    client = DraftClient(Credential(), transport=httpx.MockTransport(handle))
    client.request("POST", "drafts/draft_1/validate", idempotency_key=KEY, json={"expected_revision": 1})
    assert len(seen) == 2 and {r.headers["Idempotency-Key"] for r in seen} == {KEY}
    assert client.http.follow_redirects is False
    assert OUTPUT_SCHEMA["oneOf"][0]["properties"]["data"]["additionalProperties"] is False


@pytest.mark.parametrize("changes", [{"view_mode": "default"}, {"view_mode": None}, {"view_enforced_by": "client"},
                                      {"migration_pairs": []}, {"migration_pairs": [{"source_vendor": "fortinet", "target_vendor": "palo_alto_set"}]}])
def test_strict_enforcement_and_explicit_pair_required_before_local_read(tmp_path, monkeypatch, changes):
    monkeypatch.setattr("netconverter_cli.drafts.secure_snapshot", lambda *a, **k: pytest.fail("No file read"))
    svc, seen = service(tmp_path, lambda req: pytest.fail("No upload"), capabilities(**changes))
    assert svc.call("prepare_draft", {"path": "source.cfg", "idempotency_key": KEY})["error"]["code"] == "unsupported_capability"
    assert len(seen) == 1
    assert seen[0].headers["X-NetConverter-View"] == "strict"


def test_every_request_demands_server_strict_view(tmp_path):
    svc, seen = service(tmp_path, lambda req: success(draft(validation_status="passed")))
    result = svc.call("validate_draft", args())
    assert result["ok"]
    assert len(seen) == 3
    assert all(req.headers["X-NetConverter-View"] == "strict" for req in seen)


@pytest.mark.parametrize("action,arguments", [
    ("propose_changes", args(yaml_path="secret.yaml")),
    ("validate_draft", args()), ("request_review", args()),
    ("execute_approved", args(approval_ref="approval_1")),
    ("export_document", {"draft_id": "draft_1", "revision": 1}),
])
def test_other_draft_kind_pair_blocks_mutation_download_and_yaml_read(tmp_path, monkeypatch, action, arguments):
    monkeypatch.setattr("netconverter_cli.drafts.secure_snapshot", lambda *a, **k: pytest.fail("No file read"))
    def handle(request):
        assert action == "execute_approved" and request.method == "GET"
        assert request.url.path.endswith("/approval-status")
        return success(approved())
    svc, seen = service(tmp_path, handle, metadata=draft(source_vendor="fortinet"))
    assert svc.call(action, arguments)["error"]["code"] == "unsupported_capability"
    assert len(seen) == (3 if action == "execute_approved" else 2)
    assert all(req.method == "GET" for req in seen)


def test_redirect_body_cannot_claim_success(tmp_path):
    svc, seen = service(tmp_path, lambda req: httpx.Response(302, headers={"Location": "https://other.example"}, json={"success": True, "data": draft()}))
    result = svc.call("validate_draft", args())
    assert result["ok"] is False
    assert len(seen) == 3


@pytest.mark.parametrize("source_hash", [None, "0" * 64])
def test_prepare_response_must_bind_uploaded_source_hash(tmp_path, source_hash):
    (tmp_path / "source.cfg").write_text("synthetic")
    svc, _ = service(tmp_path, lambda req: success(draft(source_sha256=source_hash)))
    result = svc.call("prepare_draft", {"path": "source.cfg", "idempotency_key": KEY})
    assert result["error"]["code"] == "invalid_response"


def test_same_revision_contradictory_approval_content_does_not_execute(tmp_path):
    def handle(request):
        assert request.method == "GET"
        return success(approved(content_sha256="0" * 64, validated_content_sha256="0" * 64))
    svc, seen = service(tmp_path, handle)
    result = svc.call("execute_approved", args(approval_ref="approval_1"))
    assert result["error"]["code"] == "approval_required"
    assert not any(request.method == "POST" for request in seen)


@pytest.mark.parametrize("malformed", [
    {"required_decisions": [{"decision_id": "private-hostname"}]},
    {"required_decisions": [{"decision_id": "dec_" + "1" * 32, "choices": [{"choice_id": "PRIVATE_servername"}]}]},
    {"required_decisions": [{"decision_id": "dec_" + "1" * 32, "required": "yes"}]},
    {"required_decisions": [None]}, {"required_decisions": "empty"},
    {"coverage": {"unparsed": -1}}, {"status": "arbitrary_text"},
    {"required_decisions": [{"decision_id": "dec_" + "1" * 32, "entity_ref": CANARY}]},
])
def test_malformed_known_projection_fields_fail_closed(tmp_path, malformed):
    svc, _ = service(tmp_path, lambda req: success(draft(**malformed)))
    result = svc.call("validate_draft", args())
    assert result["error"]["code"] == "invalid_response"
    assert CANARY not in json.dumps(result)


def test_structured_changes_require_minted_opaque_references(tmp_path):
    svc, seen = service(tmp_path, lambda req: success(draft(revision=2)))
    good = {"decision_id": "dec_" + "1" * 32, "choice_id": "cho_" + "2" * 32, "entity_ref": "ent_" + "3" * 32}
    assert svc.call("propose_changes", args(changes=[good]))["ok"]
    for field in good:
        invalid = dict(good, **{field: CANARY})
        assert svc.call("propose_changes", args(changes=[invalid]))["error"]["code"] == "invalid_arguments"
    assert len([request for request in seen if request.method == "POST"]) == 1


def test_actual_json_schema_validates_projected_success_and_errors(tmp_path):
    from jsonschema import Draft202012Validator
    Draft202012Validator.check_schema(OUTPUT_SCHEMA)
    validator = Draft202012Validator(OUTPUT_SCHEMA)
    svc, _ = service(tmp_path, lambda req: success(draft(validation_status="passed")))
    for response in [svc.capabilities(), svc.call("validate_draft", args()), svc.call("validate_draft", args(revision=True))]:
        validator.validate(response)
    with pytest.raises(Exception) as error:
        validator.validate({"schema_version": "1", "ok": True, "data": {"source_config": CANARY}})
    assert error.type.__name__ == "ValidationError"
