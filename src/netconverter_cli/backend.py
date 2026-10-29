"""Which NetConverter API a credential reaches, and the full-API job path.

Shared by the full-screen app and the local MCP bridge so the two can never
disagree about what a credential may do. ``external``: an ``nck_*`` key or a
Clerk sign-in on the full External API (``/jobs``, any supported vendor).
``quick``: a 0.1.x Terminal Quick pilot key, whose scopes never reach
``/jobs`` (the server answers 403), limited to ASA → Palo Alto.
"""

from __future__ import annotations

import hashlib
import json

from .api import APIError, Client, ExternalClient
from .catalog import JOB_TYPES, device_type_of
from .job_options import external_body

# Full External API inline-submit ceiling (server: 5 MB).
EXTERNAL_MAX_BYTES = 5 * 1024 * 1024
QUICK_JOB_TYPES = frozenset({"convert", "optimize"})


def detect_profile(credential, server, *, transport=None) -> tuple[str, frozenset]:
    """('external', job types /me advertises) or ('quick', pilot job types).

    Raises APIError when neither surface accepts the credential.
    """
    client = ExternalClient(credential, server, transport=transport)
    try:
        try:
            me = client.me()
        except APIError as exc:
            if exc.status != 403 or getattr(credential, "kind", "key") != "key":
                raise
            quick = Client(credential, server, transport=transport)
            try:
                quick.capabilities()
            finally:
                quick.close()
            return "quick", QUICK_JOB_TYPES
        advertised = me.get("job_types") if isinstance(me, dict) else None
        types = frozenset(t for t in advertised or ["convert"] if t in JOB_TYPES)
        return "external", types or frozenset({"convert"})
    finally:
        client.close()


def open_client(credential, server, *, transport=None):
    """(client, profile) for the full-screen app and the plain CLI."""
    kind, _ = detect_profile(credential, server, transport=transport)
    cls = ExternalClient if kind == "external" else Client
    return cls(credential, server, transport=transport), kind


def submit_external(client, content: bytes, source_vendor: str, target_vendor, job_type: str,
                    options: dict, idempotency_key: str, *, allow_document: bool = True):
    """POST /jobs with inline UTF-8 text. ``technology`` follows the vendor code.

    Options go through ``job_options``: an option the server would ignore is
    refused (OptionsError) and guided settings travel as ``yaml_v2`` (#11, #19).
    """
    settings = external_body(options, job_type, target_vendor, allow_document=allow_document)
    text = content.decode("utf-8")  # callers snapshot UTF-8 text only
    body = {**settings, "source_vendor": source_vendor, "source_config": text,
            "technology": device_type_of(source_vendor)}
    if target_vendor:
        body["target_vendor"] = target_vendor
    if job_type != "convert":
        body["job_type"] = job_type
    return client.submit_job(body, idempotency_key)


ANALYSIS_RESULTS = {"validate": "validation", "optimize": "optimization"}


def _save_json(output, job_id: str, filename: str, value):
    # Canonical bytes keep a repeat download identical (JSONB key order).
    content = json.dumps(value, indent=2, sort_keys=True, default=str).encode()
    return output.save_artifact(job_id, filename, content, hashlib.sha256(content).hexdigest())


def download_external(client, job_id: str, output) -> list:
    """Translated config, the structured report and the evidence workbook, hash-verified.

    A validate or optimize job emits no translation: GET /jobs/{id} carries its
    result, saved as ``<job>.validation.json`` / ``<job>.optimization.json``.
    """
    saved = []
    job = client.job(job_id)
    key = ANALYSIS_RESULTS.get(job.get("job_type")) if isinstance(job, dict) else None
    if key:
        result = job.get(key)
        if result is None:
            raise APIError(409, "job_not_completed", detail={"job_id": job_id, "status": job.get("status")})
        saved.append(_save_json(output, job_id, f"{key}.json", {
            "job_id": job_id, "job_type": job["job_type"], "status": job.get("status"),
            "source_vendor": job.get("source_vendor"), key: result}))
        workbook = client.evidence_workbook(job_id)
        if workbook:
            saved.append(output.save_artifact(job_id, "evidence.xlsx", workbook,
                                              hashlib.sha256(workbook).hexdigest()))
        return saved
    translated = client.translated(job_id)
    if translated:
        saved.append(output.save_artifact(job_id, "translated.txt", translated,
                                          hashlib.sha256(translated).hexdigest()))
    saved.append(_save_json(output, job_id, "report.json", client.report(job_id)))
    workbook = client.evidence_workbook(job_id)
    if workbook:
        saved.append(output.save_artifact(job_id, "evidence.xlsx", workbook,
                                          hashlib.sha256(workbook).hexdigest()))
    return saved
