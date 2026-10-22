"""Clerk sign-in: PKCE/state, loopback callback, device flow, refresh, keyring.

All HTTP to the sign-in server is mocked (httpx.MockTransport) and the
keyring backend is an in-memory fake. These tests do not prove the live Clerk
instance accepts the flow; that needs the redirect URI registered and a real
sign-in.
"""

import base64
import hashlib
import json
import threading
import time
from urllib.parse import parse_qs, urlsplit

import httpx
import keyring
import pytest

from netconverter_cli import clerk, credentials
from netconverter_cli.api import Client
from netconverter_cli.clerk import (
    CLIENT_ID,
    ISSUER,
    REDIRECT_URI,
    ClerkError,
    ClerkSession,
    TokenSet,
    TokenStore,
)

DISCOVERY = {
    "issuer": ISSUER,
    "authorization_endpoint": ISSUER + "/oauth/authorize",
    "token_endpoint": ISSUER + "/oauth/token",
    "revocation_endpoint": ISSUER + "/oauth/token/revoke",
    "device_authorization_endpoint": ISSUER + "/oauth/device_authorization",
    "grant_types_supported": ["authorization_code", "refresh_token", clerk.DEVICE_GRANT],
    "code_challenge_methods_supported": ["S256"],
}
OIDC = {"issuer": ISSUER, "userinfo_endpoint": ISSUER + "/oauth/userinfo"}


class MemoryKeyring:
    """In-memory stand-in that passes the OS-backend check."""

    def __init__(self):
        self.items = {}

    def get_password(self, service, name):
        return self.items.get((service, name))

    def set_password(self, service, name, value):
        self.items[(service, name)] = value

    def delete_password(self, service, name):
        self.items.pop((service, name), None)


MemoryKeyring.__module__ = "keyring.backends.macOS"


class PlaintextKeyring(MemoryKeyring):
    pass


PlaintextKeyring.__module__ = "keyrings.alt.file"


@pytest.fixture
def vault(monkeypatch):
    backend = MemoryKeyring()
    monkeypatch.setattr(keyring, "get_keyring", lambda: backend)
    return backend


def oauth_server(token_handler=None, calls=None):
    calls = calls if calls is not None else []

    def handler(request):
        calls.append(request)
        path = request.url.path
        if path == "/.well-known/oauth-authorization-server":
            return httpx.Response(200, json=DISCOVERY)
        if path == "/.well-known/openid-configuration":
            return httpx.Response(200, json=OIDC)
        if path == "/oauth/token" and token_handler:
            return token_handler(request)
        if path == "/oauth/userinfo":
            return httpx.Response(200, json={"email": "pilot@example.test", "name": "Pilot",
                                             "org_id": "org_synthetic"})
        if path == "/oauth/token/revoke":
            return httpx.Response(200, json={})
        return httpx.Response(404, json={})

    return httpx.MockTransport(handler), calls


def form(request):
    return {k: v[0] for k, v in parse_qs(request.content.decode()).items()}


def test_pkce_s256_and_authorization_url():
    verifier, challenge = clerk.pkce_pair()
    assert 43 <= len(verifier) <= 128
    expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    assert challenge == expected and "=" not in challenge
    disc = clerk.Discovery(ISSUER, DISCOVERY["authorization_endpoint"], DISCOVERY["token_endpoint"])
    url = clerk.authorization_url(disc, "STATE123", challenge)
    query = {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}
    assert query["code_challenge_method"] == "S256"
    assert query["code_challenge"] == challenge
    assert query["state"] == "STATE123"
    assert query["client_id"] == CLIENT_ID
    assert query["redirect_uri"] == REDIRECT_URI == "http://127.0.0.1:33419/callback"
    assert "offline_access" in query["scope"]
    assert verifier not in url


def test_callback_validation_state_issuer_and_error():
    assert clerk.parse_callback(f"code=abc&state=s1&iss={ISSUER}", "s1", ISSUER) == "abc"
    with pytest.raises(ClerkError, match="state mismatch"):
        clerk.parse_callback("code=abc&state=forged", "s1", ISSUER)
    with pytest.raises(ClerkError, match="state mismatch"):
        clerk.parse_callback("code=abc", "s1", ISSUER)
    with pytest.raises(ClerkError, match="unexpected issuer"):
        clerk.parse_callback("code=abc&state=s1&iss=https://evil.example", "s1", ISSUER)
    with pytest.raises(ClerkError) as exc:
        clerk.parse_callback("error=invalid_scope&error_description=bad+scope&state=s1", "s1", ISSUER)
    assert "invalid_scope" in str(exc.value) and "scopes" in str(exc.value)
    with pytest.raises(ClerkError, match="no authorization code"):
        clerk.parse_callback("state=s1", "s1", ISSUER)


def test_discovery_is_read_at_runtime_and_checked():
    transport, _ = oauth_server()
    with httpx.Client(transport=transport) as http:
        disc = clerk.discover(http)
    assert disc.device_authorization_endpoint.endswith("/oauth/device_authorization")
    assert disc.userinfo_endpoint == ISSUER + "/oauth/userinfo"

    def tampered(request):
        doc = dict(DISCOVERY, token_endpoint="https://attacker.example/token")
        return httpx.Response(200, json=doc)

    with httpx.Client(transport=httpx.MockTransport(tampered)) as http:
        with pytest.raises(ClerkError, match="unexpected token_endpoint"):
            clerk.discover(http)

    def wrong_issuer(request):
        return httpx.Response(200, json=dict(DISCOVERY, issuer="https://other.example"))

    with httpx.Client(transport=httpx.MockTransport(wrong_issuer)) as http:
        with pytest.raises(ClerkError, match="issuer"):
            clerk.discover(http)

    def no_device(request):
        if request.url.path.endswith("oauth-authorization-server"):
            return httpx.Response(200, json=dict(DISCOVERY, grant_types_supported=["authorization_code"]))
        return httpx.Response(404)

    with httpx.Client(transport=httpx.MockTransport(no_device)) as http:
        disc = clerk.discover(http)
        assert disc.device_authorization_endpoint is None
        with pytest.raises(ClerkError, match="device sign-in"):
            clerk.device_login(http, disc, notify=lambda _: None)


def test_browser_flow_end_to_end_on_loopback(vault):
    """Simulated browser + Clerk: the callback server, state, PKCE and exchange."""
    seen = {}

    def tokens(request):
        body = form(request)
        seen["token_form"] = body
        challenge = seen["challenge"]
        assert body["grant_type"] == "authorization_code"
        assert body["code"] == "AUTH_CODE"
        assert base64.urlsafe_b64encode(
            hashlib.sha256(body["code_verifier"].encode()).digest()
        ).rstrip(b"=").decode() == challenge
        return httpx.Response(200, json={"access_token": "AT1", "refresh_token": "RT1",
                                         "expires_in": 3600, "token_type": "Bearer"})

    transport, _ = oauth_server(tokens)

    def browser(url):
        query = {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}
        seen["challenge"] = query["code_challenge"]
        redirect = query["redirect_uri"]
        assert urlsplit(redirect).hostname == "127.0.0.1"

        def visit():
            # Stray request first (favicon) must not end the wait.
            httpx.get(redirect.replace("/callback", "/favicon.ico"), timeout=5)
            seen["page"] = httpx.get(
                f"{redirect}?code=AUTH_CODE&state={query['state']}&iss={ISSUER}", timeout=5
            ).text

        seen["thread"] = threading.Thread(target=visit, daemon=True)
        seen["thread"].start()

    with httpx.Client(transport=transport) as http:
        disc = clerk.discover(http)
        result = clerk.browser_login(http, disc, open_browser=browser, notify=lambda _: None,
                                     port=0, timeout=10)
    assert result.access_token == "AT1" and result.refresh_token == "RT1"
    seen["thread"].join(5)
    assert seen["token_form"]["redirect_uri"].startswith("http://127.0.0.1:")
    assert "Signed in" in seen["page"] and "AUTH_CODE" not in seen["page"]


def test_callback_server_reports_error_redirect_and_times_out():
    server = clerk.CallbackServer("good-state", ISSUER, port=0)
    assert server.httpd.server_address[0] == "127.0.0.1"
    url = f"http://127.0.0.1:{server.port}/callback?error=invalid_scope&state=good-state"
    threading.Thread(target=lambda: httpx.get(url, timeout=5), daemon=True).start()
    with pytest.raises(ClerkError, match="invalid_scope"):
        server.wait(timeout=10)

    idle = clerk.CallbackServer("s", ISSUER, port=0)
    started = time.monotonic()
    with pytest.raises(ClerkError, match="Timed out"):
        idle.wait(timeout=0.3)
    assert time.monotonic() - started < 5

    forged = clerk.CallbackServer("expected", ISSUER, port=0)
    url = f"http://127.0.0.1:{forged.port}/callback?code=X&state=forged"
    threading.Thread(target=lambda: httpx.get(url, timeout=5), daemon=True).start()
    with pytest.raises(ClerkError, match="state mismatch"):
        forged.wait(timeout=10)


def test_device_flow_polls_with_backoff():
    replies = iter([
        httpx.Response(400, json={"error": "authorization_pending"}),
        httpx.Response(400, json={"error": "slow_down"}),
        httpx.Response(200, json={"access_token": "DAT", "refresh_token": "DRT", "expires_in": 60}),
    ])

    def handler(request):
        if request.url.path == "/oauth/device_authorization":
            assert form(request)["client_id"] == CLIENT_ID
            return httpx.Response(200, json={"device_code": "DC", "user_code": "ABCD-EFGH",
                                             "verification_uri": ISSUER + "/device", "interval": 5,
                                             "expires_in": 600})
        assert form(request)["grant_type"] == clerk.DEVICE_GRANT
        return next(replies)

    sleeps, shown = [], []
    disc = clerk.Discovery(ISSUER, DISCOVERY["authorization_endpoint"], DISCOVERY["token_endpoint"],
                           DISCOVERY["device_authorization_endpoint"])
    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        tokens = clerk.device_login(http, disc, notify=shown.append, sleep=sleeps.append,
                                    clock=lambda: 0)
    assert tokens.access_token == "DAT"
    assert sleeps == [5, 5, 10]
    assert any("ABCD-EFGH" in line for line in shown)

    def denied(request):
        if request.url.path == "/oauth/device_authorization":
            return httpx.Response(200, json={"device_code": "DC", "user_code": "X",
                                             "verification_uri": ISSUER + "/device"})
        return httpx.Response(400, json={"error": "access_denied"})

    with httpx.Client(transport=httpx.MockTransport(denied)) as http:
        with pytest.raises(ClerkError, match="denied"):
            clerk.device_login(http, disc, notify=lambda _: None, sleep=lambda _: None, clock=lambda: 0)


def test_keyring_storage_never_touches_disk(vault, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    store = TokenStore()
    assert store.save(TokenSet("ACCESS_SECRET", "REFRESH_SECRET", 1234.0, "openid"))
    names = {name for (_, name) in vault.items}
    assert names == {store.account + s for s in (":access", ":refresh", ":meta")}
    assert all(service == credentials.SERVICE for (service, _) in vault.items)
    assert "ACCESS_SECRET" not in vault.items[(credentials.SERVICE, store.account + ":meta")]
    loaded = store.load()
    assert (loaded.access_token, loaded.refresh_token, loaded.expires_at) == ("ACCESS_SECRET", "REFRESH_SECRET", 1234.0)
    assert list(tmp_path.iterdir()) == []
    assert store.clear() and store.load() is None and vault.items == {}


def test_plaintext_keyring_backend_is_refused(monkeypatch):
    monkeypatch.setattr(keyring, "get_keyring", lambda: PlaintextKeyring())
    assert not credentials.keyring_available()
    assert not TokenStore().save(TokenSet("A", "R", 1.0))
    with pytest.raises(ClerkError, match="credential store"):
        clerk.login(transport=httpx.MockTransport(lambda r: httpx.Response(500)))


def test_session_refreshes_on_expiry_and_rotates(vault):
    store = TokenStore()
    store.save(TokenSet("OLD", "RT_OLD", expires_at=100.0))

    def tokens(request):
        body = form(request)
        assert body == {"grant_type": "refresh_token", "refresh_token": "RT_OLD", "client_id": CLIENT_ID,
                        "resource": "https://api.netconverter.ai/mcp/v1"}
        return httpx.Response(200, json={"access_token": "NEW", "refresh_token": "RT_NEW", "expires_in": 3600})

    transport, _ = oauth_server(tokens)
    session = ClerkSession(store, transport=transport, clock=lambda: 1000.0)
    assert session.token() == "NEW"
    assert store.load().refresh_token == "RT_NEW"


def test_api_401_triggers_one_refresh_and_retry(vault):
    store = TokenStore()
    store.save(TokenSet("STALE", "RT", expires_at=time.time() + 3600))
    transport, _ = oauth_server(lambda r: httpx.Response(200, json={
        "access_token": "FRESH", "expires_in": 3600}))
    session = ClerkSession(store, transport=transport)
    seen = []

    def api(request):
        seen.append(request.headers["Authorization"])
        if request.headers["Authorization"] == "Bearer FRESH":
            return httpx.Response(200, json={"success": True, "data": {"profile": "x"}})
        return httpx.Response(401, json={"success": False, "error": {"code": "unauthorized"}})

    client = Client(session, "https://api.example/external/v1", transport=httpx.MockTransport(api))
    assert client.capabilities() == {"profile": "x"}
    assert seen == ["Bearer STALE", "Bearer FRESH"]
    assert store.load().refresh_token == "RT"  # kept when not rotated


def test_invalid_grant_clears_tokens(vault):
    store = TokenStore()
    store.save(TokenSet("OLD", "REVOKED", expires_at=0.0))
    transport, _ = oauth_server(lambda r: httpx.Response(400, json={"error": "invalid_grant"}))
    session = ClerkSession(store, transport=transport, clock=lambda: 1000.0)
    with pytest.raises(ClerkError, match="login --clerk"):
        session.token()
    assert store.load() is None


def test_logout_revokes_and_clears(vault):
    store = TokenStore()
    store.save(TokenSet("AT", "RT", expires_at=time.time() + 3600))
    transport, calls = oauth_server()
    assert ClerkSession(store, transport=transport).revoke_and_clear()
    revoked = [form(c)["token_type_hint"] for c in calls if c.url.path == "/oauth/token/revoke"]
    assert revoked == ["refresh_token", "access_token"]
    assert vault.items == {}


def test_whoami_shows_identity_without_tokens(vault, tmp_path, monkeypatch, capsys):
    from netconverter_cli import cli

    TokenStore().save(TokenSet("TOKEN_MUST_NOT_PRINT", "REFRESH_MUST_NOT_PRINT", time.time() + 3600))
    transport, _ = oauth_server()
    real = clerk.ClerkSession
    monkeypatch.setattr(clerk, "ClerkSession", lambda *a, **k: real(*a, transport=transport, **k))
    monkeypatch.delenv("NETCONVERTER_API_KEY", raising=False)
    cli.main(["--workspace", str(tmp_path), "whoami"])
    out = capsys.readouterr()
    assert "TOKEN_MUST_NOT_PRINT" not in out.out + out.err
    assert "REFRESH_MUST_NOT_PRINT" not in out.out + out.err
    data = json.loads(out.out)
    assert data["clerk"]["email"] == "pilot@example.test"
    assert data["clerk"]["organizations"] == ["org_synthetic"]


def test_login_defaults_to_key_unless_clerk_is_opted_in(tmp_path, monkeypatch):
    from netconverter_cli import cli

    calls = []
    monkeypatch.setattr(cli, "clerk_login", lambda args, settings: calls.append("clerk"))
    monkeypatch.setattr(cli.getpass, "getpass", lambda _: (_ for _ in ()).throw(RuntimeError("key path")))
    monkeypatch.delenv("NETCONVERTER_AUTH", raising=False)
    with pytest.raises(RuntimeError, match="key path"):
        cli.main(["--workspace", str(tmp_path), "login"])
    cli.main(["--workspace", str(tmp_path), "login", "--clerk"])
    cli.main(["--workspace", str(tmp_path), "login", "--device"])
    monkeypatch.setenv("NETCONVERTER_AUTH", "clerk")
    cli.main(["--workspace", str(tmp_path), "login"])
    with pytest.raises(RuntimeError, match="key path"):
        cli.main(["--workspace", str(tmp_path), "login", "--key"])
    assert calls == ["clerk", "clerk", "clerk"]


def test_every_token_request_names_the_mcp_resource():
    """The server's audience check names /mcp/v1 (REST applies the same
    check), so authorize, code exchange, refresh and device flow all send the
    RFC 8707 resource indicator — as Claude Code does."""
    from urllib.parse import parse_qs, urlsplit

    from netconverter_cli import clerk

    disc = clerk.Discovery(issuer=clerk.ISSUER,
                           authorization_endpoint="https://clerk.netconverter.ai/oauth/authorize",
                           token_endpoint="https://clerk.netconverter.ai/oauth/token")
    url = clerk.authorization_url(disc, "s", "c")
    assert parse_qs(urlsplit(url).query)["resource"] == [clerk.RESOURCE]
    import inspect

    src = inspect.getsource(clerk)
    assert src.count('"resource": RESOURCE') >= 4


def test_oauth_error_keeps_the_cause_sentence_of_a_long_description():
    """#684: Clerk's cause was cut off at 200 characters."""
    from netconverter_cli.clerk import OAuthError
    cause = "This OAuth application does not have the 'urn:ietf:params:oauth:grant-type:device_code' grant."
    exc = OAuthError("unauthorized_client", {"error_description": "x" * 230 + " " + cause})
    assert cause in str(exc)


def test_profile_summary_shows_the_org_name_not_its_raw_id():
    from netconverter_cli.clerk import profile_summary
    info = {"org_id": "org_39VBTisVKmTSYHZamQtGhl8y9rS", "org_slug": "nexthopllc", "org_name": "NextHop LLC"}
    assert profile_summary(info)["organizations"] == ["NextHop LLC"]
    assert profile_summary({"org_id": "org_X"})["organizations"] == ["org_X"]
