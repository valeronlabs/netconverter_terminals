"""Clerk OAuth 2.1 sign-in for the terminal (public client, PKCE S256).

Endpoints are read from the issuer's discovery document at runtime; only the
issuer, the public client id, the scopes and the loopback callback are fixed
here. Tokens live only in the OS credential store (``credentials.py``) or in
memory; they are never written to the workspace, printed, or given to a model.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import html
import json
import re
import secrets
import threading
import time
import webbrowser
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx

from .credentials import delete_secret, keyring_available, load_secret, save_secret

ISSUER = "https://clerk.netconverter.ai"
CLIENT_ID = "RjSv1z2Gms6iS96s"
SCOPES = "openid profile email offline_access user:org:read"
# RFC 8707 resource indicator. The server's audience check names the MCP
# resource; Claude Code sends the same value, and NetConverter's REST door
# applies the identical check, so one token works for both.
RESOURCE = "https://api.netconverter.ai/mcp/v1"
# Dedicated loopback callback for this client (Claude Code uses 33418).
CALLBACK_HOST = "127.0.0.1"
CALLBACK_PORT = 33419
CALLBACK_PATH = "/callback"
REDIRECT_URI = f"http://{CALLBACK_HOST}:{CALLBACK_PORT}{CALLBACK_PATH}"
CALLBACK_TIMEOUT_S = 300
DEVICE_GRANT = "urn:ietf:params:oauth:grant-type:device_code"
# Refresh this many seconds before the access token's stated expiry.
EXPIRY_SKEW_S = 60


class ClerkError(RuntimeError):
    """A sign-in failure with a message safe to show (never a token)."""


def _safe_text(value, limit: int = 200) -> str:
    text = re.sub(r"[^\x20-\x7e]", "", str(value or ""))
    return text[:limit]


def _http(transport=None) -> httpx.Client:
    return httpx.Client(
        timeout=30, follow_redirects=False, trust_env=False, transport=transport
    )


# --------------------------------------------------------------------------
# Discovery
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Discovery:
    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    device_authorization_endpoint: str | None = None
    revocation_endpoint: str | None = None
    userinfo_endpoint: str | None = None


def _endpoint(doc: dict, key: str, issuer_host: str, required: bool) -> str | None:
    value = doc.get(key)
    if not value:
        if required:
            raise ClerkError(f"Sign-in server discovery is missing {key}")
        return None
    parts = urlsplit(str(value))
    if parts.scheme != "https" or parts.hostname != issuer_host:
        raise ClerkError(f"Sign-in server advertised an unexpected {key}")
    return str(value)


def discover(http: httpx.Client, issuer: str = ISSUER) -> Discovery:
    issuer = issuer.rstrip("/")
    host = urlsplit(issuer).hostname or ""
    try:
        response = http.get(issuer + "/.well-known/oauth-authorization-server")
        response.raise_for_status()
        doc = response.json()
    except (httpx.HTTPError, ValueError):
        raise ClerkError("Could not read the sign-in server discovery document") from None
    if not isinstance(doc, dict) or str(doc.get("issuer", "")).rstrip("/") != issuer:
        raise ClerkError("Sign-in server discovery issuer does not match")
    methods = doc.get("code_challenge_methods_supported")
    if methods is not None and "S256" not in methods:
        raise ClerkError("Sign-in server does not support PKCE S256")
    userinfo = None
    try:
        oidc = http.get(issuer + "/.well-known/openid-configuration")
        if oidc.status_code == 200:
            meta = oidc.json()
            if str(meta.get("issuer", "")).rstrip("/") == issuer:
                userinfo = _endpoint(meta, "userinfo_endpoint", host, False)
    except (httpx.HTTPError, ValueError, ClerkError):
        userinfo = None
    return Discovery(
        issuer=issuer,
        authorization_endpoint=_endpoint(doc, "authorization_endpoint", host, True),
        token_endpoint=_endpoint(doc, "token_endpoint", host, True),
        device_authorization_endpoint=_endpoint(
            doc, "device_authorization_endpoint", host, False
        )
        if DEVICE_GRANT in (doc.get("grant_types_supported") or [DEVICE_GRANT])
        else None,
        revocation_endpoint=_endpoint(doc, "revocation_endpoint", host, False),
        userinfo_endpoint=userinfo
        or _endpoint(doc, "userinfo_endpoint", host, False),
    )


# --------------------------------------------------------------------------
# Tokens
# --------------------------------------------------------------------------


@dataclass
class TokenSet:
    access_token: str
    refresh_token: str = ""
    expires_at: float = 0.0
    scope: str = ""
    token_type: str = "Bearer"

    @classmethod
    def from_response(cls, body, now: float, previous_refresh: str = "") -> "TokenSet":
        if not isinstance(body, dict) or not isinstance(body.get("access_token"), str):
            raise ClerkError("Sign-in server returned no access token")
        if str(body.get("token_type", "Bearer")).lower() != "bearer":
            raise ClerkError("Sign-in server returned an unsupported token type")
        try:
            lifetime = int(body.get("expires_in", 3600))
        except (TypeError, ValueError):
            lifetime = 3600
        return cls(
            access_token=body["access_token"],
            # Refresh tokens may rotate; keep the previous one if none is returned.
            refresh_token=body.get("refresh_token") or previous_refresh,
            expires_at=now + max(lifetime, 0),
            scope=str(body.get("scope", "")),
        )

    def expired(self, now: float) -> bool:
        return now >= self.expires_at - EXPIRY_SKEW_S


def _token_request(http: httpx.Client, disc: Discovery, form: dict) -> dict:
    try:
        response = http.post(
            disc.token_endpoint, data=form, headers={"Accept": "application/json"}
        )
    except httpx.HTTPError:
        raise ClerkError("Could not reach the sign-in server") from None
    try:
        body = response.json()
    except ValueError:
        body = {}
    if response.is_error:
        error = _safe_text(body.get("error") if isinstance(body, dict) else "", 60)
        raise OAuthError(error or f"http_{response.status_code}", body)
    return body


class OAuthError(ClerkError):
    def __init__(self, error: str, body=None):
        description = ""
        if isinstance(body, dict):
            # Clerk puts the cause in the last sentence; keep the whole description, not a cut-off head.
            description = _safe_text(body.get("error_description"), 600)
        super().__init__(
            f"Sign-in refused: {error}" + (f" ({description})" if description else "")
        )
        self.error = error


def exchange_code(
    http: httpx.Client, disc: Discovery, code: str, verifier: str,
    redirect_uri: str = REDIRECT_URI, client_id: str = CLIENT_ID,
) -> TokenSet:
    body = _token_request(
        http,
        disc,
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": client_id,
            "code_verifier": verifier,
            "resource": RESOURCE,
        },
    )
    return TokenSet.from_response(body, time.time())


def refresh_tokens(
    http: httpx.Client, disc: Discovery, refresh_token: str, client_id: str = CLIENT_ID
) -> TokenSet:
    body = _token_request(
        http,
        disc,
        {"grant_type": "refresh_token", "refresh_token": refresh_token, "client_id": client_id,
         "resource": RESOURCE},
    )
    return TokenSet.from_response(body, time.time(), previous_refresh=refresh_token)


# --------------------------------------------------------------------------
# Browser flow (authorization code + PKCE S256, loopback redirect)
# --------------------------------------------------------------------------


def pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)[:96]  # RFC 7636: 43-128 characters
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def authorization_url(
    disc: Discovery, state: str, challenge: str,
    redirect_uri: str = REDIRECT_URI, client_id: str = CLIENT_ID, scopes: str = SCOPES,
) -> str:
    query = urlencode(
        {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scope": scopes,
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "resource": RESOURCE,
        }
    )
    separator = "&" if urlsplit(disc.authorization_endpoint).query else "?"
    return disc.authorization_endpoint + separator + query


def parse_callback(query: str, expected_state: str, issuer: str) -> str:
    """Validate a redirect's query string and return the authorization code."""
    params = {k: v[0] for k, v in parse_qs(query, keep_blank_values=True).items()}
    state = params.get("state", "")
    if not state or not hmac.compare_digest(state.encode(), expected_state.encode()):
        raise ClerkError(
            "Sign-in response did not match this request (state mismatch); start again"
        )
    # RFC 9207: when present, the issuer must be the one we started with.
    if "iss" in params and params["iss"].rstrip("/") != issuer.rstrip("/"):
        raise ClerkError("Sign-in response came from an unexpected issuer")
    if "error" in params:
        error = _safe_text(params["error"], 60)
        description = _safe_text(params.get("error_description"))
        hint = {
            "invalid_scope": "the OAuth application does not allow the requested scopes",
            "access_denied": "sign-in was cancelled or denied",
            "invalid_request": "the OAuth application rejected the request "
            f"(is {REDIRECT_URI} a registered redirect URI?)",
            "unauthorized_client": "this OAuth client may not use this sign-in method",
        }.get(error, "")
        raise ClerkError(
            f"Sign-in failed: {error}"
            + (f" — {hint}" if hint else "")
            + (f" ({description})" if description else "")
        )
    code = params.get("code", "")
    if not code:
        raise ClerkError("Sign-in response contained no authorization code")
    return code


_DONE_PAGE = (
    "<!doctype html><meta charset=utf-8><title>NetConverter sign-in</title>"
    "<body style='font-family:system-ui;background:#0b0d10;color:#e6e8eb;padding:3em'>"
    "<h1>{title}</h1><p>{message}</p><p>You can close this window and return to the terminal.</p>"
)


class _CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 - http.server API
        parts = urlsplit(self.path)
        if parts.path != CALLBACK_PATH:
            self.send_response(404)
            self.end_headers()
            return
        try:
            code = parse_callback(parts.query, self.server.expected_state, self.server.issuer)
            self.server.result = ("ok", code)
            title, message = "Signed in", "NetConverter received your sign-in."
        except ClerkError as exc:
            self.server.result = ("error", str(exc))
            title, message = "Sign-in failed", str(exc)
        page = _DONE_PAGE.format(title=html.escape(title), message=html.escape(message))
        body = page.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # keep codes and states out of the terminal
        return


class CallbackServer:
    """One-shot loopback listener bound only to 127.0.0.1."""

    def __init__(self, expected_state: str, issuer: str, port: int = CALLBACK_PORT):
        try:
            self.httpd = HTTPServer((CALLBACK_HOST, port), _CallbackHandler)
        except OSError:
            raise ClerkError(
                f"Port {port} on {CALLBACK_HOST} is busy; close the other sign-in "
                "or use `netconverter login --clerk --device`"
            ) from None
        self.httpd.expected_state = expected_state
        self.httpd.issuer = issuer
        self.httpd.result = None
        self.port = self.httpd.server_address[1]

    def wait(self, timeout: float = CALLBACK_TIMEOUT_S, clock=time.monotonic) -> str:
        deadline = clock() + timeout
        try:
            while self.httpd.result is None:
                remaining = deadline - clock()
                if remaining <= 0:
                    raise ClerkError(
                        "Timed out waiting for the browser sign-in; run the command again"
                    )
                self.httpd.timeout = min(remaining, 1.0)
                self.httpd.handle_request()
        finally:
            self.httpd.server_close()
        kind, value = self.httpd.result
        if kind != "ok":
            raise ClerkError(value)
        return value


def browser_login(
    http: httpx.Client, disc: Discovery, *, open_browser=webbrowser.open, notify=print,
    port: int = CALLBACK_PORT, timeout: float = CALLBACK_TIMEOUT_S,
) -> TokenSet:
    verifier, challenge = pkce_pair()
    state = secrets.token_urlsafe(32)
    server = CallbackServer(state, disc.issuer, port)
    redirect_uri = f"http://{CALLBACK_HOST}:{server.port}{CALLBACK_PATH}"
    url = authorization_url(disc, state, challenge, redirect_uri)
    notify("Opening your browser to sign in to NetConverter.")
    notify(f"If it does not open, visit:\n{url}")
    try:
        open_browser(url)
    except Exception:
        pass
    code = server.wait(timeout)
    return exchange_code(http, disc, code, verifier, redirect_uri)


# --------------------------------------------------------------------------
# Device flow (RFC 8628) for headless machines
# --------------------------------------------------------------------------


def device_login(
    http: httpx.Client, disc: Discovery, *, notify=print,
    sleep=time.sleep, clock=time.monotonic, client_id: str = CLIENT_ID, scopes: str = SCOPES,
) -> TokenSet:
    if not disc.device_authorization_endpoint:
        raise ClerkError("This sign-in server does not offer device sign-in; use the browser flow")
    try:
        response = http.post(
            disc.device_authorization_endpoint,
            data={"client_id": client_id, "scope": scopes, "resource": RESOURCE},
            headers={"Accept": "application/json"},
        )
        body = response.json()
    except (httpx.HTTPError, ValueError):
        raise ClerkError("Could not start device sign-in") from None
    if response.is_error or not isinstance(body, dict) or "device_code" not in body:
        raise OAuthError(_safe_text(body.get("error") if isinstance(body, dict) else "", 60)
                         or "device_authorization_failed", body)
    verification = body.get("verification_uri_complete") or body.get("verification_uri")
    if not verification or urlsplit(str(verification)).scheme != "https":
        raise ClerkError("Device sign-in returned no usable verification address")
    notify(f"To sign in, visit {_safe_text(verification, 300)}")
    notify(f"and confirm the code: {_safe_text(body.get('user_code'), 40)}")
    interval = max(int(body.get("interval", 5) or 5), 1)
    deadline = clock() + int(body.get("expires_in", 600) or 600)
    while clock() < deadline:
        sleep(interval)
        try:
            token = _token_request(
                http,
                disc,
                {"grant_type": DEVICE_GRANT, "device_code": body["device_code"], "client_id": client_id},
            )
        except OAuthError as exc:
            if exc.error == "authorization_pending":
                continue
            if exc.error == "slow_down":
                interval += 5
                continue
            if exc.error == "access_denied":
                raise ClerkError("Device sign-in was denied") from None
            if exc.error == "expired_token":
                break
            raise
        return TokenSet.from_response(token, time.time())
    raise ClerkError("Device sign-in code expired; run the command again")


# --------------------------------------------------------------------------
# Keyring storage and the refreshing session credential
# --------------------------------------------------------------------------


class TokenStore:
    """Clerk tokens in the OS credential store; separate entries keep each small."""

    def __init__(self, issuer: str = ISSUER, client_id: str = CLIENT_ID):
        digest = hashlib.sha256(f"{issuer.rstrip('/')}|{client_id}".encode()).hexdigest()
        self.account = "clerk:" + digest[:24]

    def save(self, tokens: TokenSet) -> bool:
        meta = json.dumps(
            {"expires_at": tokens.expires_at, "scope": tokens.scope, "token_type": "Bearer"}
        )
        ok = save_secret(self.account + ":refresh", tokens.refresh_token or "")
        ok = ok and save_secret(self.account + ":access", tokens.access_token)
        ok = ok and save_secret(self.account + ":meta", meta)
        if not ok:
            self.clear()
        return ok

    def load(self) -> TokenSet | None:
        access = load_secret(self.account + ":access")
        if not access:
            return None
        try:
            meta = json.loads(load_secret(self.account + ":meta") or "{}")
        except ValueError:
            meta = {}
        return TokenSet(
            access_token=access,
            refresh_token=load_secret(self.account + ":refresh"),
            expires_at=float(meta.get("expires_at", 0) or 0),
            scope=str(meta.get("scope", "")),
        )

    def clear(self) -> bool:
        results = [delete_secret(self.account + suffix) for suffix in (":access", ":refresh", ":meta")]
        return all(results)


class ClerkSession:
    """Credential for ``api.BearerAuth``: refreshes on expiry and after a 401."""

    kind = "clerk"

    def __init__(self, store: TokenStore | None = None, issuer: str = ISSUER,
                 *, transport=None, clock=time.time):
        self.store = store or TokenStore(issuer)
        self.issuer = issuer
        self._transport = transport
        self._clock = clock
        self._tokens = self.store.load()
        self._discovery: Discovery | None = None
        self._lock = threading.Lock()

    @property
    def signed_in(self) -> bool:
        return self._tokens is not None

    def _disc(self, http) -> Discovery:
        if self._discovery is None:
            self._discovery = discover(http, self.issuer)
        return self._discovery

    def token(self) -> str:
        with self._lock:
            if self._tokens is None:
                raise ClerkError("Not signed in; run `netconverter login --clerk`")
            if self._tokens.expired(self._clock()) and self._tokens.refresh_token:
                self._refresh_locked()
            return self._tokens.access_token

    def refresh(self) -> bool:
        with self._lock:
            if self._tokens is None or not self._tokens.refresh_token:
                return False
            try:
                self._refresh_locked()
                return True
            except ClerkError:
                return False

    def _refresh_locked(self) -> None:
        with _http(self._transport) as http:
            try:
                tokens = refresh_tokens(http, self._disc(http), self._tokens.refresh_token)
            except OAuthError as exc:
                if exc.error in {"invalid_grant", "invalid_token", "unauthorized_client"}:
                    self.store.clear()
                    self._tokens = None
                    raise ClerkError(
                        "Your NetConverter sign-in expired; run `netconverter login --clerk`"
                    ) from None
                raise
        self._tokens = tokens
        self.store.save(tokens)

    def userinfo(self) -> dict:
        with _http(self._transport) as http:
            disc = self._disc(http)
            if not disc.userinfo_endpoint:
                return {}
            for attempt in range(2):
                response = http.get(
                    disc.userinfo_endpoint,
                    headers={"Authorization": f"Bearer {self.token()}"},
                )
                if response.status_code == 401 and attempt == 0 and self.refresh():
                    continue
                break
            if response.is_error:
                raise ClerkError(f"Could not read the signed-in profile (HTTP {response.status_code})")
            try:
                return response.json()
            except ValueError:
                return {}

    def revoke_and_clear(self) -> bool:
        tokens, self._tokens = self._tokens, None
        if tokens:
            try:
                with _http(self._transport) as http:
                    disc = self._disc(http)
                    if disc.revocation_endpoint:
                        for value, hint in ((tokens.refresh_token, "refresh_token"),
                                            (tokens.access_token, "access_token")):
                            if value:
                                http.post(disc.revocation_endpoint, data={
                                    "token": value, "token_type_hint": hint, "client_id": CLIENT_ID})
            except (httpx.HTTPError, ClerkError):
                pass  # local removal below is what logout guarantees
        return self.store.clear()


UNNAMED_ORG = "(unnamed organization)"


def profile_summary(info: dict) -> dict:
    """Non-secret identity fields for display; never tokens."""
    out = {}
    for key in ("email", "name", "preferred_username"):
        if isinstance(info.get(key), str) and info[key]:
            out[key] = _safe_text(info[key], 120)
    # One label per organization: its name, else its slug, else UNNAMED_ORG; never the raw id.
    # Entries that share an id (the active org and its membership entry) are one organization.
    orgs: dict = {}

    def add(org_id, name, slug):
        label = next((v for v in (name, slug) if isinstance(v, str) and v.strip()), None)
        label = _safe_text(label, 120) if label else None
        if isinstance(org_id, str) and org_id:
            key = ("id", org_id)
        elif label:
            key = ("label", label)
        else:
            return  # nothing identifies it
        if not orgs.get(key):
            orgs[key] = label

    if any(isinstance(info.get(k), str) and info[k] for k in ("org_id", "org_name", "org_slug")):
        add(info.get("org_id"), info.get("org_name"), info.get("org_slug"))
    for org in info.get("organizations") or info.get("orgs") or []:
        if isinstance(org, dict):
            add(org.get("id"), org.get("name"), org.get("slug"))
    # A label-only entry naming an org already known by id is the same organization.
    named = {label for (kind, _), label in orgs.items() if kind == "id" and label}
    labels = [label or UNNAMED_ORG for (kind, _), label in orgs.items()
              if not (kind == "label" and label in named)]
    if labels:
        out["organizations"] = sorted(labels)
    return out


def login(
    *, device: bool = False, issuer: str = ISSUER, transport=None,
    notify=print, open_browser=webbrowser.open, store: TokenStore | None = None,
) -> TokenSet:
    """Sign in and store tokens. Refuses when no OS credential store exists."""
    if store is None and not keyring_available():
        raise ClerkError(
            "No OS credential store is available; Clerk sign-in needs one to keep tokens off disk"
        )
    store = store or TokenStore(issuer)
    with _http(transport) as http:
        disc = discover(http, issuer)
        tokens = (
            device_login(http, disc, notify=notify)
            if device
            else browser_login(http, disc, open_browser=open_browser, notify=notify)
        )
    if not store.save(tokens):
        raise ClerkError("Could not save the sign-in to the OS credential store")
    return tokens
