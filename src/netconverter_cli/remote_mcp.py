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
# The server's view modes (External MCP access grants). The bridge may ask the
# server to LOWER the grant's view for this session; it can never raise it.
VIEW_MODES = ("default", "strict", "full_addresses")
VIEW_HEADER = "X-NetConverter-View"


class RemoteError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _short(value, limit=300) -> str:
    return "".join(ch for ch in str(value or "") if ch.isprintable())[:limit]


class RemoteMCP:
    def __init__(self, url: str, credential, *, transport=None, client_version="0", view_mode=None):
        self.url = check_url(url)
        if view_mode is not None and view_mode not in VIEW_MODES:
            raise ValueError("Unknown view mode")
        self.view_mode = view_mode  # requested on every request (#15); the server decides
        self._account_view: str | None = None
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
        if self.view_mode:
            headers[VIEW_HEADER] = self.view_mode
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

    def account_view(self) -> str | None:
        """The view mode the server applies to this session (``get_account.view_mode``), once.

        None when the server does not say (an older server, a refused call).
        """
        if self._account_view is None:
            payload = self.call_tool("get_account", {})
            self._account_view = _view_mode_of(payload) or ""
        return self._account_view or None


def _view_mode_of(payload) -> str | None:
    """``data.view_mode`` from a get_account result: structuredContent first, else its JSON text."""
    candidates = []
    if isinstance(payload, dict):
        candidates.append(payload.get("structuredContent"))
        for item in payload.get("content") or []:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                try:
                    candidates.append(json.loads(item["text"]))
                except ValueError:
                    continue
    for candidate in candidates:
        data = candidate.get("data") if isinstance(candidate, dict) else None
        data = data if isinstance(data, dict) else candidate
        if isinstance(data, dict) and data.get("view_mode") in VIEW_MODES:
            return data["view_mode"]
    return None
