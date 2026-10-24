"""CLI contract proofs use synthetic HTTP responses, never live server jobs."""

import json
import hashlib

import httpx
import pytest
from jsonschema import Draft202012Validator

from netconverter_cli import cli, drafts


def install_transport(monkeypatch, handler):
    original = drafts.DraftClient
    monkeypatch.setattr(drafts, "DraftClient", lambda key, server: original(
        key, server, transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(cli, "rest_credential", lambda *a, **kw: "synthetic-key")
    monkeypatch.setattr(cli.Provider, "__init__", lambda *a, **kw: pytest.fail("draft created an AI provider"))


def test_unsupported_server_does_not_read_or_submit(tmp_path, monkeypatch, capsys):
    requests = []

    def server(request):
        requests.append(request)
        return httpx.Response(200, json={"success": True, "data": {"job_types": ["convert"]}})

    install_transport(monkeypatch, server)
    with pytest.raises(SystemExit) as exc:
        cli.main(["--workspace", str(tmp_path), "--provider", "openai", "draft", "prepare",
                  "missing.conf", "--idempotency-key", "prepare-0001"])
    assert exc.value.code == 1
    result = json.loads(capsys.readouterr().out)
    assert result["error"]["code"] == "unsupported_capability"
    assert [(r.method, r.url.path) for r in requests] == [("GET", "/external/v1/capabilities")]


def test_missing_credentials_never_prompt(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NETCONVERTER_AUTH", "key")

    def secret(*args, **kwargs):
        assert kwargs["prompt"] is False
        return ""

    monkeypatch.setattr(cli, "get_secret", secret)
    with pytest.raises(SystemExit) as exc:
        cli.main(["--workspace", str(tmp_path), "draft", "decisions", "dr_123", "--revision", "1"])
    assert exc.value.code == 1
    result = json.loads(capsys.readouterr().out)
    assert result["error"]["code"] == "access_denied"


def test_workspace_cannot_redirect_draft_signin(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "workspace_settings", lambda args: {"server": "https://attacker.example/external/v1"})
    monkeypatch.setattr(cli, "rest_credential", lambda *a, **kw: pytest.fail("credential accessed for untrusted workspace server"))
    with pytest.raises(SystemExit, match="not a trusted NetConverter host"):
        cli.main(["--workspace", str(tmp_path), "draft", "decisions", "dr_123", "--revision", "1"])


@pytest.mark.parametrize("revision", ["0", "-1", "yes", "1.5"])
def test_invalid_revision_rejected_before_io(revision):
    with pytest.raises(SystemExit):
        cli.parser().parse_args(["draft", "validate", "dr_123", "--revision", revision,
                                "--idempotency-key", "validate-001"])


def test_all_mutations_require_explicit_retry_key():
    for arguments in (["prepare", "source.conf"], ["validate", "dr_123", "--revision", "1"],
                      ["review", "dr_123", "--revision", "1"],
                      ["execute", "dr_123", "--revision", "1", "--approval-ref", "ap_123"]):
        with pytest.raises(SystemExit):
            cli.parser().parse_args(["draft", *arguments])


def test_bad_proposal_json_is_safe_and_does_not_call_server(tmp_path, monkeypatch, capsys):
    install_transport(monkeypatch, lambda request: pytest.fail("invalid JSON reached network"))
    with pytest.raises(SystemExit):
        cli.main(["--workspace", str(tmp_path), "draft", "propose", "dr_123", "--revision", "1",
                  "--idempotency-key", "propose-001", "--changes", "PRIVATE_CANARY_INVALID_JSON"])
    out = capsys.readouterr().out
    assert json.loads(out)["error"]["code"] == "invalid_arguments"
    assert "PRIVATE_CANARY" not in out


def test_guided_mcp_forces_strict_without_constructing_remote(tmp_path, monkeypatch):
    from netconverter_cli import mcp_server, remote_mcp

    monkeypatch.setattr(cli, "choose_mcp_credential", lambda *a: ("key", "key", "synthetic", []))
    monkeypatch.setattr(remote_mcp, "RemoteMCP", lambda *a, **kw: pytest.fail("guided mode created legacy proxy"))
    seen = []
    monkeypatch.setattr(mcp_server, "run_stdio", lambda bridge: seen.append(bridge))
    cli.main(["--workspace", str(tmp_path), "mcp", "--guided"])
    assert len(seen) == 1
    assert seen[0].guided and seen[0].strict and seen[0].remote is None


def test_manual_yaml_workflow_uses_revisions_without_ai(tmp_path, monkeypatch, capsys):
    """One CLI trace against a synthetic, explicitly enabled contract server."""
    source = "hostname SYNTHETIC_PRIVATE_CANARY\n"
    (tmp_path / "source.cfg").write_text(source)
    state = {"revision": 1, "document": "decisions: {}\n", "approved": False}
    requests = []
    sha = lambda value: hashlib.sha256(value.encode()).hexdigest()

    def metadata(**extra):
        return {"draft_id": "draft_1", "revision": state["revision"], "draft_kind": "migration",
                "source_vendor": "cisco_asa", "target_vendor": "palo_alto_set",
                "content_sha256": sha(state["document"]), "source_sha256": sha(source), **extra}

    def response(data):
        return httpx.Response(200, json={"success": True, "data": data})

    def server(request):
        requests.append(request)
        assert request.headers["X-NetConverter-View"] == "strict"
        path = request.url.path.removeprefix("/external/v1/")
        if path == "capabilities":
            return response({"guided_workflows": {
                "contract_version": "1", "enabled": True, "approval_mode": "human_bound",
                "agent_restricted": True, "view_mode": "strict", "view_enforced_by": "server",
                "operations": list(drafts.ACTIONS),
                "migration_pairs": [{"source_vendor": "cisco_asa", "target_vendor": "palo_alto_set"}],
            }})
        if request.method == "GET" and path.startswith("drafts/"):
            assert request.url.params["revision"] == str(state["revision"])
        if path == "drafts":
            body = json.loads(request.content)
            assert body["source_config"] == source and body["source_sha256"] == sha(source)
            return response(metadata(status="prepared", source_config=source))
        if path == "drafts/draft_1":
            return response(metadata(required_decisions=[]))
        if path.endswith("/document"):
            return response(metadata(document=state["document"], sha256=sha(state["document"])))
        if path.endswith("/proposals"):
            body = json.loads(request.content)
            assert body["expected_revision"] == state["revision"]
            assert body["document_sha256"] == sha(body["document"])
            state["document"] = body["document"]
            state["revision"] += 1
            return response(metadata(status="prepared", document=state["document"]))
        if path.endswith("/validate"):
            assert json.loads(request.content) == {"expected_revision": state["revision"]}
            return response(metadata(validation_status="passed"))
        if path.endswith("/review-requests"):
            return response(metadata(review_id="review_1", status="pending_review",
                review_url="https://api.netconverter.ai/external/v1/drafts/draft_1/reviews/review_1"))
        if path.endswith("/approval-status"):
            return response(metadata(status="approved" if state["approved"] else "pending_review",
                approval_ref="approval_1", human_bound=state["approved"], validation_status="passed",
                validated_content_sha256=sha(state["document"])))
        if path == "jobs":
            assert state["approved"]
            assert json.loads(request.content) == {"approved_draft_id": "draft_1",
                "draft_revision": 2, "approval_ref": "approval_1"}
            return response({"job_id": "job_1", "status": "queued"})
        pytest.fail("Unexpected contract route")

    install_transport(monkeypatch, server)

    def invoke(*arguments, failure=False):
        command = ["--workspace", str(tmp_path), "--provider", "openai", "draft", *arguments]
        if failure:
            with pytest.raises(SystemExit) as exc:
                cli.main(command)
            assert exc.value.code == 1
        else:
            cli.main(command)
        output = capsys.readouterr().out
        result = json.loads(output)
        Draft202012Validator(drafts.OUTPUT_SCHEMA).validate(result)
        assert "SYNTHETIC_PRIVATE_CANARY" not in output
        return result

    assert invoke("prepare", "source.cfg", "--idempotency-key", "prepare-0001")["ok"]
    assert invoke("decisions", "draft_1", "--revision", "1")["ok"]
    exported = invoke("export", "draft_1", "--revision", "1")
    from pathlib import Path
    document = Path(exported["data"]["path"])
    document.write_text("decisions: {retire: SYNTHETIC_PRIVATE_CANARY}\n")
    imported = invoke("import", "draft_1", "--revision", "1", "--yaml", str(document),
                      "--idempotency-key", "import-00001")
    assert imported["data"]["revision"] == 2
    invoke("validate", "draft_1", "--revision", "2", "--idempotency-key", "validate-001")
    invoke("review", "draft_1", "--revision", "2", "--idempotency-key", "review-00001")
    execute = ("execute", "draft_1", "--revision", "2", "--approval-ref", "approval_1",
               "--idempotency-key", "execute-0001")
    assert invoke(*execute, failure=True)["error"]["code"] == "approval_required"
    assert not any(r.method == "POST" and r.url.path.endswith("/jobs") for r in requests)
    state["approved"] = True  # separate synthetic human action, never a client tool
    assert invoke(*execute)["data"]["job_id"] == "job_1"
    assert (tmp_path / "source.cfg").read_text() == source
    assert len([r for r in requests if r.method == "POST" and r.url.path.endswith("/jobs")]) == 1
