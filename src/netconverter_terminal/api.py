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


class Client:
    def __init__(self, key: str, base: str = DEFAULT_BASE, *, transport=None):
        parts = urlsplit(base)
        if parts.username or parts.password or parts.query or parts.fragment:
            raise ValueError("Invalid server URL")
        if parts.scheme != "https" and not (
            parts.scheme == "http"
            and parts.hostname in {"127.0.0.1", "localhost", "::1"}
        ):
            raise ValueError(
                "Server connections require HTTPS (HTTP only for explicit loopback testing)"
            )
        self.http = httpx.Client(
            base_url=base.rstrip("/") + "/",
            timeout=60,
            headers={"Authorization": f"Bearer {key}"},
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

    def request(
        self, method: str, path: str, *, idempotency_key: str | None = None, **kwargs
    ):
        if not path.startswith("quick/") or ".." in path or ":" in path or "?" in path:
            raise ValueError("Only the restricted quick API may be called")
        headers = {"X-Request-ID": "req_" + uuid.uuid4().hex}
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        try:
            response = self.http.request(method, path, headers=headers, **kwargs)
        except httpx.HTTPError:
            raise APIError(0, "connection_failed", headers["X-Request-ID"]) from None
        try:
            body = response.json()
        except ValueError:
            raise APIError(
                response.status_code, "invalid_response", headers["X-Request-ID"]
            ) from None
        if response.is_error or body.get("success") is not True:
            error = body.get("error", {})
            raise APIError(
                response.status_code,
                str(error.get("code", "request_failed")),
                body.get("request_id", headers["X-Request-ID"]),
                body.get("detail", error.get("detail")),
            )
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
