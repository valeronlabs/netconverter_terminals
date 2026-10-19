"""Direct NetConverter data channel. No model SDK imports belong here."""

from __future__ import annotations

import re
import uuid
from urllib.parse import urlsplit

import httpx

DEFAULT_BASE = "https://api.netconverter.ai/external/v1"


class APIError(RuntimeError):
    def __init__(self, status: int, code: str, request_id: str = "", detail=None):
        super().__init__(
            f"NetConverter {code} (HTTP {status}, request {request_id or 'unavailable'})"
        )
        self.status, self.code, self.request_id, self.detail = (
            status,
            code,
            request_id,
            detail,
        )


def check_url(base: str) -> str:
    """HTTPS only (HTTP for explicit loopback testing); no userinfo/query/fragment."""
    parts = urlsplit(base)
    if parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError("Invalid server URL")
    if parts.scheme != "https" and not (
        parts.scheme == "http" and parts.hostname in {"127.0.0.1", "localhost", "::1"}
    ):
        raise ValueError(
            "Server connections require HTTPS (HTTP only for explicit loopback testing)"
        )
    return base


class StaticCredential:
    """An API key (``nck_*`` or terminal_quick). It cannot be refreshed."""

    kind = "key"

    def __init__(self, key: str):
        self._key = key

    def token(self) -> str:
        return self._key

    def refresh(self) -> bool:
        return False


class BearerAuth(httpx.Auth):
    """Bearer from a credential; one refresh-and-retry on HTTP 401.

    Works for static keys (no retry) and for Clerk OAuth sessions, whose
    ``token()`` refreshes an expiring access token and whose ``refresh()``
    forces a refresh after the server rejected the current one.
    """

    requires_request_body = True

    def __init__(self, credential):
        self.credential = credential

    def auth_flow(self, request):
        request.headers["Authorization"] = f"Bearer {self.credential.token()}"
        response = yield request
        if response.status_code == 401 and self.credential.refresh():
            request.headers["Authorization"] = f"Bearer {self.credential.token()}"
            yield request


def as_credential(key):
    return StaticCredential(key) if isinstance(key, str) else key


class Client:
    # Path allowlist for this client's restricted surface.
    _ALLOWED = re.compile(r"quick/[A-Za-z0-9_/-]{1,200}\Z")

    def __init__(self, key, base: str = DEFAULT_BASE, *, transport=None):
        check_url(base)
        self.credential = as_credential(key)
        self.http = httpx.Client(
            base_url=base.rstrip("/") + "/",
            timeout=60,
            auth=BearerAuth(self.credential),
            transport=transport,
            follow_redirects=False,
            trust_env=False,
        )

    def close(self):
        self.http.close()

    @staticmethod
    def identifier(value: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", value):
            raise ValueError("Invalid resource identifier")
        return value

    def _send(self, method, path, idempotency_key=None, **kwargs):
        if not self._ALLOWED.fullmatch(path) or ".." in path:
            raise ValueError("Only the restricted NetConverter API may be called")
        headers = {"X-Request-ID": "req_" + uuid.uuid4().hex}
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        try:
            response = self.http.request(method, path, headers=headers, **kwargs)
        except httpx.HTTPError:
            raise APIError(0, "connection_failed", headers["X-Request-ID"]) from None
        return response, headers["X-Request-ID"]

    @staticmethod
    def _error(response, request_id):
        try:
            body = response.json()
        except ValueError:
            return APIError(response.status_code, "invalid_response", request_id)
        error = body.get("error", {}) if isinstance(body, dict) else {}
        if not isinstance(error, dict):
            error = {}
        return APIError(
            response.status_code,
            str(error.get("code", "request_failed")),
            body.get("request_id", request_id) if isinstance(body, dict) else request_id,
            body.get("detail", error.get("detail")) if isinstance(body, dict) else None,
        )

    def request(
        self, method: str, path: str, *, idempotency_key: str | None = None, **kwargs
    ):
        response, request_id = self._send(method, path, idempotency_key, **kwargs)
        try:
            body = response.json()
        except ValueError:
            raise APIError(response.status_code, "invalid_response", request_id) from None
        if response.is_error or not isinstance(body, dict) or body.get("success") is not True:
            raise self._error(response, request_id)
        return body["data"]

    def capabilities(self):
        return self.request("GET", "quick/capabilities")

    def upload(self, content: bytes, vendor: str):
        return self.request(
            "POST", "quick/configurations", content=content, params={"vendor": vendor}
        )

    def submit(
        self, configuration_id: str, operation: str, options: dict, idempotency_key: str
    ):
        return self.request(
            "POST",
            "quick/jobs",
            idempotency_key=idempotency_key,
            json={
                "configuration_id": configuration_id,
                "operation": operation,
                "options": options,
            },
        )

    def jobs(self):
        return self.request("GET", "quick/jobs")

    def status(self, job_id: str):
        return self.request("GET", f"quick/jobs/{self.identifier(job_id)}")

    def query(
        self,
        job_id: str,
        operation: str,
        arguments: dict,
        idempotency_key: str,
        offset: int = 0,
    ):
        return self.request(
            "POST",
            "quick/queries",
            idempotency_key=idempotency_key,
            json={
                "job_id": job_id,
                "operation": operation,
                "arguments": arguments,
                "offset": offset,
            },
        )

    def target(self, job_id: str):
        return self.request("POST", f"quick/jobs/{self.identifier(job_id)}/target")

    def artifacts(self, job_id: str):
        return self.request("GET", f"quick/jobs/{self.identifier(job_id)}/artifacts")

    def download(self, job_id: str, artifact_id: str):
        return self.request(
            "GET",
            f"quick/jobs/{self.identifier(job_id)}/artifacts/{self.identifier(artifact_id)}",
        )


class ExternalClient(Client):
    """Full External API v1 (``/jobs``, ``/me``, ``/capabilities``), same Bearer handling.

    Accepts ``nck_*`` keys and Clerk OAuth access tokens.
    """

    _ALLOWED = re.compile(
        r"(?:me|capabilities|jobs|jobs/[A-Za-z0-9_-]{1,80}(?:/translated|/report|/evidence\.xlsx)?)\Z"
    )

    def me(self):
        return self.request("GET", "me")

    def capabilities(self):
        """Vendors, source→target paths, job types and limits POST /jobs accepts."""
        return self.request("GET", "capabilities")

    def jobs(self, limit: int = 25):
        data = self.request("GET", "jobs", params={"comparable": "false", "limit": limit})
        return data.get("jobs", []) if isinstance(data, dict) else []

    def evidence_workbook(self, job_id: str) -> bytes | None:
        """The customer evidence workbook; None when this job has none."""
        response, request_id = self._send(
            "GET", f"jobs/{self.identifier(job_id)}/evidence.xlsx"
        )
        if response.status_code in (404, 409, 422):
            return None
        if response.is_error:
            raise self._error(response, request_id)
        return response.content

    def submit_job(self, body: dict, idempotency_key: str):
        return self.request("POST", "jobs", idempotency_key=idempotency_key, json=body)

    def job(self, job_id: str):
        return self.request("GET", f"jobs/{self.identifier(job_id)}")

    def report(self, job_id: str):
        return self.request("GET", f"jobs/{self.identifier(job_id)}/report")

    def translated(self, job_id: str) -> bytes | None:
        """Translated configuration bytes; None while absent (queued/blocked)."""
        response, request_id = self._send(
            "GET", f"jobs/{self.identifier(job_id)}/translated"
        )
        if response.status_code == 404:
            return None
        if response.is_error:
            raise self._error(response, request_id)
        return response.content
