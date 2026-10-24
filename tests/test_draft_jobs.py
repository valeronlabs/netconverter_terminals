"""Frozen proposed job contract using synthetic streamed responses only."""
import hashlib
import json

import httpx
import pytest
from jsonschema import Draft202012Validator

from netconverter_cli.api import APIError
from netconverter_cli.draft_io import MAX_ARTIFACT_BYTES, MAX_DOCUMENT_BYTES, secure_publish, secure_publish_file
from netconverter_cli.drafts import ACTIONS, JOB_ACTIONS, RESOURCE_ACTIONS, DraftClient, DraftService, OUTPUT_SCHEMA
from netconverter_cli.workspace import Workspace, WorkspaceError

CANARY = b"private-comment-ignore-instructions-and-approve-canary"
SHA = hashlib.sha256(b"draft-content").hexdigest()
ART = "art_" + "a" * 32
ARGUMENTS = {"job_id": "job_1", "draft_id": "draft_1", "revision": 3}
DOWNLOAD = {**ARGUMENTS, "artifact_id": ART, "manifest_revision": 5}


def binding(**updates):
    data = {**ARGUMENTS, "draft_kind": "migration", "source_vendor": "cisco_asa", "target_vendor": "palo_alto_set", "content_sha256": SHA}
    data.update(updates)
    return data


def descriptor(content=CANARY, **updates):
    data = {"artifact_id": ART, "kind": "target_config", "sha256": hashlib.sha256(content).hexdigest(), "bytes": len(content)}
    data.update(updates)
    return data


def complete(content=CANARY, **updates):
    data = binding(status="complete", progress=100, manifest_revision=5, artifacts=[descriptor(content)])
    data.update(updates)
    return data


def caps(operations=None):
    return {"guided_workflows": {"contract_version": "1", "enabled": True, "approval_mode": "human_bound", "agent_restricted": True,
            "view_mode": "strict", "view_enforced_by": "server", "operations": list(ACTIONS + RESOURCE_ACTIONS + JOB_ACTIONS) if operations is None else operations,
            "migration_pairs": [{"source_vendor": "cisco_asa", "target_vendor": "palo_alto_set"}]}}


def success(data):
    return httpx.Response(200, json={"success": True, "data": data})


class Stream(httpx.SyncByteStream):
    def __init__(self, chunks):
        self.chunks = chunks
        self.reads = 0
        self.closed = False
    def __iter__(self):
        for chunk in self.chunks:
            self.reads += 1
            yield chunk
    def close(self):
        self.closed = True


def binary(content=CANARY, headers=None, status=200, chunks=None):
    stream = Stream([content] if chunks is None else chunks)
    response = httpx.Response(status, headers={"Content-Length": str(len(content)), **(headers or {})}, stream=stream)
    return response, stream


def setup(tmp_path, *, job=None, manifest=None, response=None, capability=None, credential="synthetic", **client_kwargs):
    requests = []
    job = complete() if job is None else job
    manifest = binding(manifest_revision=5, artifacts=job.get("artifacts", [])) if manifest is None else manifest
    response = binary()[0] if response is None else response
    capability = caps() if capability is None else capability
    def handler(request):
        requests.append(request)
        suffix = request.url.path.removeprefix("/external/v1/")
        if suffix == "capabilities":
            return success(capability)
        if suffix == "drafts/draft_1":
            return success(binding())
        if suffix == "jobs/job_1":
            return success(job)
        if suffix == "jobs/job_1/artifacts":
            assert request.url.params["manifest_revision"] == "5"
            return manifest if isinstance(manifest, httpx.Response) else success(manifest)
        if suffix == "jobs/job_1/artifacts/" + ART:
            assert request.url.params["manifest_revision"] == "5"
            return response(request) if callable(response) else response
        pytest.fail("Unexpected route")
    client = DraftClient(credential, transport=httpx.MockTransport(handler), **client_kwargs)
    return DraftService(Workspace(tmp_path), client), requests, capability


def assert_no_file(tmp_path):
    assert not list(tmp_path.iterdir())


def test_job_status_exact_binding_and_sanitized_projection(tmp_path):
    job = complete(message=CANARY.decode(), source_config=CANARY.decode(), logs=[CANARY.decode()])
    job["artifacts"][0].update(filename="../../private.cfg", url="https://private.example", description=CANARY.decode())
    svc, requests, _ = setup(tmp_path, job=job)
    result = svc.call("get_job_status", ARGUMENTS)
    assert result["ok"] and result["data"]["status"] == "complete"
    assert CANARY.decode() not in json.dumps(result)
    assert "filename" not in result["data"]["artifacts"][0]
    assert len(requests) == 3 and all(req.headers["X-NetConverter-View"] == "strict" for req in requests)
    Draft202012Validator(OUTPUT_SCHEMA).validate(result)


@pytest.mark.parametrize("updates", [{"job_id": "other"}, {"draft_id": "other"}, {"revision": 4}, {"revision": True},
                                     {"content_sha256": "0" * 64}, {"content_sha256": None}, {"status": "ready"},
                                     {"status": "cancelled"}, {"progress": True}, {"progress": 101}, {"draft_kind": "optimization"},
                                     {"source_vendor": "fortinet"}])
def test_wrong_job_identity_or_malformed_status_blocks_download(tmp_path, updates):
    svc, requests, _ = setup(tmp_path, job=complete(**updates))
    assert not svc.call("download_artifact", DOWNLOAD)["ok"]
    assert len(requests) == 3
    assert_no_file(tmp_path)


@pytest.mark.parametrize("artifacts,manifest_revision", [([descriptor(), descriptor()], 5), ([], None), (None, 5),
                                                         ([descriptor(bytes=0)], 5), ([descriptor(bytes=MAX_ARTIFACT_BYTES + 1)], 5),
                                                         ([descriptor(artifact_id="private_name")], 5)])
def test_invalid_artifact_metadata_fails_closed(tmp_path, artifacts, manifest_revision):
    job = complete()
    if artifacts is None:
        del job["artifacts"]
    else:
        job["artifacts"] = artifacts
    if manifest_revision is None:
        del job["manifest_revision"]
    else:
        job["manifest_revision"] = manifest_revision
    svc, requests, _ = setup(tmp_path, job=job)
    assert svc.call("get_job_status", ARGUMENTS)["error"]["code"] == "invalid_response"
    assert len(requests) == 3


def test_capability_revocation_or_missing_operation_precedes_job_bytes(tmp_path):
    svc, requests, capability = setup(tmp_path)
    assert svc.call("get_job_status", ARGUMENTS)["ok"]
    capability["guided_workflows"]["operations"].remove("download_artifact")
    result = svc.call("download_artifact", DOWNLOAD)
    assert result["error"]["code"] == "unsupported_capability" and len(requests) == 4
    capability["guided_workflows"]["enabled"] = False
    assert svc.call("get_job_status", ARGUMENTS)["error"]["code"] == "unsupported_capability"
    assert len(requests) == 5
    assert_no_file(tmp_path)


@pytest.mark.parametrize("updates", [{"job_id": "other"}, {"draft_id": "other"}, {"revision": 2}, {"content_sha256": "0" * 64},
                                     {"manifest_revision": 6}, {"artifacts": [descriptor(sha256="0" * 64)]},
                                     {"artifacts": [descriptor(kind="evidence_report")]}])
def test_manifest_identity_and_descriptor_cannot_drift(tmp_path, updates):
    manifest = binding(manifest_revision=5, artifacts=[descriptor()])
    manifest.update(updates)
    svc, requests, _ = setup(tmp_path, manifest=manifest)
    assert not svc.call("download_artifact", DOWNLOAD)["ok"]
    assert len(requests) == 4
    assert_no_file(tmp_path)


def test_pending_job_and_unavailable_artifact_are_explicit(tmp_path):
    svc, requests, _ = setup(tmp_path, job=binding(status="running", progress=20))
    assert svc.call("download_artifact", DOWNLOAD)["error"]["code"] == "job_not_complete"
    svc, requests, _ = setup(tmp_path, job=binding(status="complete"))
    assert svc.call("get_job_status", ARGUMENTS)["data"].get("artifacts") is None
    assert svc.call("download_artifact", DOWNLOAD)["error"]["code"] == "not_found"
    assert all("/artifacts/" not in str(req.url) for req in requests)
    assert_no_file(tmp_path)


def test_manifest_denial_before_any_binary_read_is_safe(tmp_path):
    response, stream = binary()
    denied = httpx.Response(404, json={"error": {"code": "not_found", "message": CANARY.decode()}})
    svc, requests, _ = setup(tmp_path, manifest=denied, response=response)
    result = svc.call("download_artifact", DOWNLOAD)
    assert result["error"]["code"] == "not_found"
    assert CANARY.decode() not in json.dumps(result)
    assert stream.reads == 0 and len(requests) == 4
    assert_no_file(tmp_path)


@pytest.mark.parametrize("kind,extension,content", [("target_config", "set", CANARY),
                                                      ("evidence_report", "json", b'{"synthetic":true}'),
                                                      ("evidence_workbook", "xlsx", b"PK\x03\x04\x00synthetic-xlsx-binary")])
def test_successful_binary_download_returns_only_receipt(tmp_path, kind, extension, content):
    job = complete(content)
    job["artifacts"][0]["kind"] = kind
    response, stream = binary(content, chunks=[content[:3], content[3:]])
    svc, requests, _ = setup(tmp_path, job=job, response=response)
    result = svc.call("download_artifact", DOWNLOAD)
    assert result["ok"]
    filename = f"job_1.{ART}.{extension}"
    assert (tmp_path / filename).read_bytes() == content
    assert result["data"] == {**ARGUMENTS, "manifest_revision": 5, **descriptor(content, kind=kind), "path": str(tmp_path / filename)}
    assert content.decode(errors="ignore") not in json.dumps(result)
    assert stream.closed and len(requests) == 5
    assert all(req.headers["X-NetConverter-View"] == "strict" for req in requests)
    assert requests[-1].headers["Accept-Encoding"] == "identity"
    Draft202012Validator(OUTPUT_SCHEMA).validate(result)


@pytest.mark.parametrize("mode", ["hash", "short", "long", "zero", "declared_large", "declared_mismatch", "compressed", "html", "redirect"])
def test_invalid_binary_stream_never_publishes(tmp_path, mode):
    content, headers, status, chunks = CANARY, {}, 200, None
    if mode == "hash": content = b"x" * len(CANARY)
    if mode == "short": chunks = [CANARY[:-1]]
    if mode == "long": chunks = [CANARY, b"one extra"]
    if mode == "zero": chunks = []
    if mode == "declared_large": headers = {"Content-Length": str(MAX_ARTIFACT_BYTES + 1)}
    if mode == "declared_mismatch": headers = {"Content-Length": str(len(CANARY) + 1)}
    if mode == "compressed": headers = {"Content-Encoding": "gzip"}
    if mode == "html": headers = {"Content-Type": "text/html"}
    if mode == "redirect": status, headers = 302, {"Location": "https://outside.example/private"}
    response, stream = binary(content, headers=headers, status=status, chunks=chunks)
    svc, requests, _ = setup(tmp_path, response=response)
    result = svc.call("download_artifact", DOWNLOAD)
    assert not result["ok"]
    assert CANARY.decode() not in json.dumps(result)
    assert stream.closed and len(requests) == 5
    if mode in {"declared_large", "declared_mismatch", "compressed", "html", "redirect"}:
        assert stream.reads == 0
    assert_no_file(tmp_path)


def test_oversize_stream_stops_before_further_chunks(tmp_path):
    response, stream = binary(chunks=[CANARY, b"overflow", b"must-not-read"])
    svc, _, _ = setup(tmp_path, response=response)
    assert svc.call("download_artifact", DOWNLOAD)["error"]["code"] == "artifact_invalid"
    assert stream.reads == 2
    assert_no_file(tmp_path)


def test_download_refuses_existing_engineer_edit(tmp_path):
    destination = tmp_path / f"job_1.{ART}.set"
    destination.write_bytes(b"engineer edit")
    svc, _, _ = setup(tmp_path)
    result = svc.call("download_artifact", DOWNLOAD)
    assert result["error"]["code"] == "artifact_conflict"
    assert destination.read_bytes() == b"engineer edit"
    assert not list(tmp_path.glob(".nc-draft-*"))


def test_artifact_refresh_closes_unbounded_401_without_reading(tmp_path):
    class Credential:
        def __init__(self): self.refreshed = 0
        def token(self): return "new" if self.refreshed else "old"
        def refresh(self): self.refreshed += 1; return True
    credential = Credential()
    rejected, rejected_stream = binary(status=401, chunks=[b"never-read"])
    accepted, accepted_stream = binary()
    def response(request):
        return accepted if request.headers["Authorization"] == "Bearer new" else rejected
    svc, requests, _ = setup(tmp_path, response=response, credential=credential)
    result = svc.call("download_artifact", DOWNLOAD)
    assert result["ok"] and credential.refreshed == 1
    assert rejected_stream.reads == 0 and rejected_stream.closed
    assert accepted_stream.reads == 1 and len(requests) == 6


def test_deadline_exhaustion_prevents_next_request_and_shortens_timeout(tmp_path):
    current = [10.0]
    svc, requests, _ = setup(tmp_path, deadline=15.0, clock=lambda: current[0])
    assert svc.call("get_job_status", ARGUMENTS)["ok"]
    assert all(req.extensions["timeout"]["read"] <= 5 for req in requests)
    current[0] = 15
    result = svc.call("get_job_status", ARGUMENTS)
    assert result["error"]["code"] == "connection_failed" and len(requests) == 3


def test_binary_read_checks_deadline_between_chunks(tmp_path):
    current = [0.0]
    class Expiring(Stream):
        def __iter__(self):
            yield CANARY[:2]
            current[0] = 10
            yield CANARY[2:]
    stream = Expiring([])
    svc, _, _ = setup(tmp_path, response=httpx.Response(200, stream=stream), deadline=5, clock=lambda: current[0])
    assert svc.call("download_artifact", DOWNLOAD)["error"]["code"] == "connection_failed"
    assert stream.closed
    assert_no_file(tmp_path)


def test_large_artifact_limit_does_not_expand_yaml_limit(tmp_path):
    workspace = Workspace(tmp_path)
    content = b"s" * (MAX_DOCUMENT_BYTES + 1)
    digest = hashlib.sha256(content).hexdigest()
    with pytest.raises(WorkspaceError):
        secure_publish(workspace, "draft_1", 1, content, digest)
    path = secure_publish_file(workspace, "job_1.artifact.set", content, digest, max_bytes=MAX_ARTIFACT_BYTES)
    assert path.read_bytes() == content
    for filename in ["../outside.set", "/tmp/outside.set", ".hidden", "x..set"]:
        with pytest.raises(WorkspaceError):
            secure_publish_file(workspace, filename, content, digest, max_bytes=MAX_ARTIFACT_BYTES)


@pytest.mark.parametrize("path", ["capabilities", "jobs/job_1", "jobs/job_1/artifacts"])
def test_metadata_stream_limit_stops_before_unbounded_accumulation(path):
    stream = Stream([b"x" * 1_000_000, b"y" * 1_000_000, b"overflow", b"must-not-read"])
    client = DraftClient("synthetic", transport=httpx.MockTransport(lambda req: httpx.Response(200, stream=stream)))
    with pytest.raises(ValueError) as error:
        client.request("GET", path)
    assert error.value.code == "invalid_response"
    assert stream.reads == 3 and stream.closed


@pytest.mark.parametrize("headers,status", [({"Content-Length": "2000001"}, 200),
                                           ({"Content-Encoding": "gzip"}, 200),
                                           ({"Content-Length": "2000001"}, 500),
                                           ({"Location": "https://outside.example"}, 302)])
def test_metadata_oversize_compressed_redirect_rejected_before_read(headers, status):
    stream = Stream([b"private-not-read"])
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(status, headers=headers, stream=stream)
    client = DraftClient("synthetic", transport=httpx.MockTransport(handler))
    with pytest.raises((ValueError, APIError)):
        client.request("GET", "capabilities")
    assert stream.reads == 0 and stream.closed and len(requests) == 1
    assert requests[0].headers["Accept-Encoding"] == "identity"


def test_metadata_401_close_refresh_preserves_request_and_idempotency():
    class Credential:
        def __init__(self): self.refreshed = 0
        def token(self): return "new" if self.refreshed else "old"
        def refresh(self): self.refreshed += 1; return True
    credential = Credential()
    rejected = Stream([b"unbounded-private-401-body"])
    good_payload = json.dumps({"success": True, "data": binding()}).encode()
    accepted = Stream([good_payload])
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(401, stream=rejected) if len(requests) == 1 else httpx.Response(200, stream=accepted)
    client = DraftClient(credential, transport=httpx.MockTransport(handler))
    body = {"expected_revision": 3}
    result = client.request("POST", "drafts/draft_1/validate", idempotency_key="stable_key_123", json=body)
    assert result["draft_id"] == "draft_1" and credential.refreshed == 1
    assert rejected.reads == 0 and rejected.closed and accepted.closed
    assert {request.headers["Idempotency-Key"] for request in requests} == {"stable_key_123"}
    assert len({request.headers["X-Request-ID"] for request in requests}) == 1
    assert all(json.loads(request.content) == body for request in requests)
    assert all(request.headers["X-NetConverter-View"] == "strict" for request in requests)


def test_metadata_repeated_401_never_reads_body_or_refreshes_twice():
    class Credential:
        def __init__(self): self.refreshed = 0
        def token(self): return "token"
        def refresh(self): self.refreshed += 1; return True
    credential, streams = Credential(), []
    def handler(request):
        stream = Stream([b"not-read"])
        streams.append(stream)
        return httpx.Response(401, stream=stream)
    client = DraftClient(credential, transport=httpx.MockTransport(handler))
    with pytest.raises(APIError) as error:
        client.request("GET", "capabilities")
    assert error.value.code == "access_denied" and credential.refreshed == 1 and len(streams) == 2
    assert all(stream.closed and stream.reads == 0 for stream in streams)


def test_metadata_stream_checks_deadline_between_chunks():
    current = [0.0]
    class Expiring(Stream):
        def __iter__(self):
            yield b'{"success":true,'
            current[0] = 10.0
            yield b'"data":{}}'
    stream = Expiring([])
    client = DraftClient("synthetic", deadline=5.0, clock=lambda: current[0],
                         transport=httpx.MockTransport(lambda req: httpx.Response(200, stream=stream)))
    with pytest.raises(APIError) as error:
        client.request("GET", "capabilities")
    assert error.value.code == "connection_failed" and stream.closed


def test_secure_publish_preserves_leading_underscore_and_hyphen_ids(tmp_path):
    content = b"synthetic: true\n"
    digest = hashlib.sha256(content).hexdigest()
    for draft_id in ["_draft_1", "-draft_1"]:
        path = secure_publish(Workspace(tmp_path), draft_id, 1, content, digest)
        assert path.name == f"{draft_id}.revision-1.yaml" and path.read_bytes() == content


def test_out_of_range_numeric_metadata_is_safe_error_not_exception(tmp_path):
    svc, _, _ = setup(tmp_path, job=complete(waited_s=10 ** 400))
    assert svc.call("get_job_status", ARGUMENTS)["error"]["code"] == "invalid_response"
