"""Minimal MCP Streamable HTTP client for NetConverter's remote read tools.

Only the configured NetConverter MCP endpoint is ever contacted (no URL comes
from a model or a tool result). Requests carry the same Bearer credential as
the REST client, with one refresh-and-retry on 401.
"""

from __future__ import annotations

import json

import httpx

from .api import BearerAuth, as_credential, check_url
from .clerk import ClerkError

DEFAULT_MCP_URL = "https://api.netconverter.ai/mcp/v1/"
CLIENT_PROTOCOL = "2025-06-18"
MAX_RESPONSE_BYTES = 8 * 1024 * 1024


class RemoteError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _short(value, limit=300) -> str:
    return "".join(ch for ch in str(value or "") if ch.isprintable())[:limit]


class RemoteMCP:
    def __init__(self, url: str, credential, *, transport=None, client_version="0"):
        self.url = check_url(url)
        self.http = httpx.Client(
            timeout=90,
            auth=BearerAuth(as_credential(credential)),
            transport=transport,
            follow_redirects=False,
            trust_env=False,
        )
        self.client_version = client_version
        self.session_id: str | None = None
        self.protocol: str | None = None
        self._initialized = False
        self._next_id = 0

    def close(self):
        self.http.close()

    # -- transport ---------------------------------------------------------

    def _headers(self) -> dict:
        headers = {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        }
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        if self.protocol:
            headers["MCP-Protocol-Version"] = self.protocol
        return headers

    def _post(self, payload: dict):
        try:
            response = self.http.post(self.url, json=payload, headers=self._headers())
        except httpx.HTTPError:
            raise RemoteError("connection_failed", "Could not reach the NetConverter MCP server") from None
        except ClerkError as exc:
            raise RemoteError("unauthorized", str(exc)) from None
        if response.status_code == 401:
            raise RemoteError(
                "unauthorized",
                "NetConverter MCP refused the credential; run `netconverter login --clerk` "
                "or store a key with `netconverter login`",
            )
        if response.status_code == 404 and self.session_id:
            raise RemoteError("session_expired", "Remote MCP session expired")
        if response.status_code == 202:
            return None
        if response.is_error:
            raise RemoteError(f"http_{response.status_code}", f"NetConverter MCP returned HTTP {response.status_code}")
        if len(response.content) > MAX_RESPONSE_BYTES:
            raise RemoteError("response_too_large", "Remote MCP response exceeded its limit")
        session = response.headers.get("mcp-session-id")
        if session:
            self.session_id = session
        content_type = response.headers.get("content-type", "")
        if "text/event-stream" in content_type:
            return self._from_sse(response.text, payload.get("id"))
        try:
            return response.json()
        except ValueError:
            raise RemoteError("invalid_response", "Remote MCP returned invalid JSON") from None

    @staticmethod
    def _from_sse(text: str, request_id):
        data: list[str] = []
        events = []
        for line in text.splitlines() + [""]:
            if line.startswith("data:"):
                data.append(line[5:].lstrip(" "))
            elif line == "" and data:
                events.append("\n".join(data))
                data = []
        for event in events:
            try:
                message = json.loads(event)
            except ValueError:
                continue
            if isinstance(message, dict) and message.get("id") == request_id and (
                "result" in message or "error" in message
            ):
                return message
        raise RemoteError("invalid_response", "Remote MCP stream contained no response")

    # -- protocol ----------------------------------------------------------

    def _request(self, method: str, params: dict | None = None) -> dict:
        self._next_id += 1
        payload = {"jsonrpc": "2.0", "id": self._next_id, "method": method}
        if params is not None:
            payload["params"] = params
        message = self._post(payload)
        if not isinstance(message, dict):
            raise RemoteError("invalid_response", "Remote MCP returned no response")
        if "error" in message:
            error = message["error"] if isinstance(message["error"], dict) else {}
            raise RemoteError(
                str(error.get("code", "error")), _short(error.get("message", "Remote MCP error"))
            )
        result = message.get("result")
        if not isinstance(result, dict):
            raise RemoteError("invalid_response", "Remote MCP returned an invalid result")
        return result

    def _initialize(self):
        result = self._request(
            "initialize",
            {
                "protocolVersion": CLIENT_PROTOCOL,
                "capabilities": {},
                "clientInfo": {"name": "netconverter-local", "version": self.client_version},
            },
        )
        version = result.get("protocolVersion")
        self.protocol = version if isinstance(version, str) and len(version) <= 20 else CLIENT_PROTOCOL
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})
        self._initialized = True

    def rpc(self, method: str, params: dict | None = None) -> dict:
        if not self._initialized:
            self._initialize()
        try:
            return self._request(method, params)
        except RemoteError as exc:
            if exc.code != "session_expired":
                raise
            self.session_id, self.protocol, self._initialized = None, None, False
            self._initialize()
            return self._request(method, params)

    def list_tools(self) -> list[dict]:
        tools: list[dict] = []
        cursor = None
        for _ in range(20):  # bounded pagination
            result = self.rpc("tools/list", {"cursor": cursor} if cursor else {})
            tools.extend(t for t in result.get("tools", []) if isinstance(t, dict) and isinstance(t.get("name"), str))
            cursor = result.get("nextCursor")
            if not cursor:
                break
        return tools

    def call_tool(self, name: str, arguments: dict) -> dict:
        return self.rpc("tools/call", {"name": name, "arguments": arguments})
