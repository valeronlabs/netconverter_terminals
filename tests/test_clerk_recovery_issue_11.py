"""Public #11: an existing MCP process recovers a renewed Clerk sign-in.

Synthetic stores and MockTransport only. No OS credentials or live requests.
"""
import json
import io
import time

import httpx
import pytest

from netconverter_cli import cli, update
from netconverter_cli.clerk import ClerkError, ClerkSession, TokenSet
from netconverter_cli.credentials import CredentialStoreError, KeyringLocked
from netconverter_cli.mcp_server import Bridge, StdioServer
from netconverter_cli.remote_mcp import RemoteMCP
from tests.test_clerk import form, oauth_server
from tests.test_mcp import AccountServer, RemoteServer


class Store:
    def __init__(self, value=None, *, clear_works=True):
        self.value = value
        self.clear_works = clear_works

    def load(self):
        return self.value

    def save(self, value):
        self.value = value
        return True

    def clear(self):
        if self.clear_works:
            self.value = None
        return self.clear_works


def tokens(name, *, expired=False):
    return TokenSet('synthetic-access-' + name, 'synthetic-refresh-' + name,
                    0 if expired else time.time() + 3600)


def failed_session(store, *, during_failure=None):
    attempts = []

    def reject(request):
        attempts.append(form(request))
        if during_failure:
            during_failure()
        return httpx.Response(400, json={'error': 'invalid_grant'})

    transport, _ = oauth_server(reject)
    return ClerkSession(store, transport=transport), attempts


def invalidate(session):
    with pytest.raises(ClerkError):
        session.token()


def rpc_account(server, request_id):
    # Actual JSON-RPC dispatch/response serialization, same server and credential.
    request = json.loads(json.dumps({'jsonrpc': '2.0', 'id': request_id,
        'method': 'tools/call', 'params': {'name': 'account', 'arguments': {}}}))
    response = json.loads(json.dumps(server.handle(request)))
    return response, json.loads(response['result']['content'][0]['text'])


def test_persistent_mcp_account_recovers_external_login_without_principal_fallback(tmp_path, monkeypatch, capsys):
    store = Store(tokens('old', expired=True))
    credential, refreshes = failed_session(store)
    api = AccountServer({'principal': {'kind': 'clerk_oauth'}, 'tier': 'professional'},
                        {'job_types': ['convert', 'validate']})
    monkeypatch.setattr(update, 'status', lambda: {'latest': None, 'update_available': None})
    bridge = Bridge(tmp_path, 'https://api.netconverter.ai/external/v1', credential,
        transport=httpx.MockTransport(api), credential_source='clerk_session',
        credential_loader=lambda: pytest.fail('must not switch to an API key or another principal'))
    server = StdioServer(bridge)
    _, first = rpc_account(server, 1)
    assert first.get('signed_in') is False or first.get('error') == 'not_signed_in'
    assert len(refreshes) == 1 and not api.requests

    # Another terminal process has saved a successful replacement login.
    replacement = tokens('renewed')
    store.save(replacement)
    response, second = rpc_account(server, 2)
    assert second.get('auth_kind') == 'clerk_oauth'
    assert second['credential_source'] == 'clerk_session'
    assert bridge.rest_credential is credential
    assert len(refreshes) == 1
    assert all(r.headers['Authorization'] == 'Bearer ' + replacement.access_token for r in api.requests)
    captured = capsys.readouterr()
    public_output = json.dumps(response) + captured.out + captured.err
    for secret in (replacement.access_token, replacement.refresh_token, 'synthetic-access-old', 'synthetic-refresh-old'):
        assert secret not in public_output


@pytest.mark.parametrize('clear_works', [True, False])
def test_invalidated_session_without_new_credentials_stays_signed_out(clear_works):
    store = Store(tokens('revoked', expired=True), clear_works=clear_works)
    session, calls = failed_session(store)
    invalidate(session)
    for _ in range(3):
        invalidate(session)
        assert session.refresh() is False
    assert len(calls) == 1  # no resurrection or revoked-token refresh loop


@pytest.mark.parametrize('replacement_timing', ['before_refresh', 'during_refresh'])
def test_stale_refresh_failure_cannot_delete_an_external_replacement(replacement_timing):
    old = tokens('old', expired=True)
    replacement = tokens('concurrent-login')
    store = Store(old)
    session, _ = failed_session(store, during_failure=(
        lambda: store.save(replacement)) if replacement_timing == 'during_refresh' else None)
    if replacement_timing == 'before_refresh':
        store.save(replacement)
    try:
        session.token()
    except ClerkError:
        pass
    assert store.load() == replacement, 'stale failure must not erase the newer login'
    assert session.token() == replacement.access_token


@pytest.mark.parametrize('clear_works', [True, False])
def test_explicit_logout_cannot_resurrect_the_same_saved_tokens(clear_works):
    original = tokens('logout')
    store = Store(original, clear_works=clear_works)
    transport, calls = oauth_server()
    session = ClerkSession(store, transport=transport)
    assert session.revoke_and_clear() is clear_works
    for _ in range(2):
        invalidate(session)
        assert session.refresh() is False
    assert not [r for r in calls if r.url.path == '/oauth/token']
    # A later deliberate login is allowed, even after explicit logout.
    replacement = tokens('after-logout')
    store.save(replacement)
    assert session.token() == replacement.access_token


def test_recovered_expired_record_uses_normal_single_refresh():
    store = Store(tokens('revoked', expired=True))
    calls = []

    def dispatch(request):
        body = form(request)
        calls.append(body)
        if body['refresh_token'] == 'synthetic-refresh-revoked':
            return httpx.Response(400, json={'error': 'invalid_grant'})
        assert body['refresh_token'] == 'synthetic-refresh-replacement'
        return httpx.Response(200, json={'access_token': 'synthetic-rotated',
            'refresh_token': 'synthetic-rotated-refresh', 'expires_in': 3600})

    transport, _ = oauth_server(dispatch)
    session = ClerkSession(store, transport=transport)
    invalidate(session)
    store.save(tokens('replacement', expired=True))
    assert session.token() == 'synthetic-rotated'
    assert session.token() == 'synthetic-rotated'
    assert len(calls) == 2
    assert all(c['resource'] == 'https://api.netconverter.ai/mcp/v1' for c in calls)


def test_refresh_entry_point_recovers_a_new_saved_session():
    store = Store(tokens('old', expired=True))
    session, _ = failed_session(store)
    invalidate(session)
    replacement = tokens('new')
    store.save(replacement)
    assert session.refresh() is True
    assert session.token() == replacement.access_token


def test_recovered_credential_still_requires_trusted_mcp_and_rest_hosts(monkeypatch):
    store = Store(tokens('old', expired=True))
    session, _ = failed_session(store)
    invalidate(session)
    replacement = tokens('new')
    store.save(replacement)
    assert session.token() == replacement.access_token
    monkeypatch.setattr(cli, '_clerk_session', lambda: session)
    monkeypatch.setattr(cli, 'get_secret', lambda *a, **k: '')
    monkeypatch.delenv('NETCONVERTER_TRUSTED_HOSTS', raising=False)
    trusted = 'https://api.netconverter.ai/external/v1'
    evil = 'https://untrusted.example.test/mcp/v1/'
    rest, remote, _, _ = cli.choose_mcp_credential('clerk', trusted, evil)
    assert rest is session and remote is None
    rest, remote, _, _ = cli.choose_mcp_credential('clerk', evil, evil)
    assert rest is None and remote is None


def test_same_stdio_line_stream_recovers_without_restarting(tmp_path, monkeypatch):
    store = Store(tokens('old', expired=True))
    credential, _ = failed_session(store)
    api = AccountServer({'principal': {'kind': 'clerk_oauth'}}, {'job_types': ['validate']})
    monkeypatch.setattr(update, 'status', lambda: {'latest': None, 'update_available': None})
    bridge = Bridge(tmp_path, 'https://api.netconverter.ai/external/v1', credential,
        transport=httpx.MockTransport(api), credential_source='clerk_session')
    server = StdioServer(bridge)

    def lines():
        yield json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {
            'protocolVersion': '2025-06-18', 'capabilities': {},
            'clientInfo': {'name': 'synthetic-recovery-verifier', 'version': '1'}}}) + '\n'
        yield json.dumps({'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call',
            'params': {'name': 'account', 'arguments': {}}}) + '\n'
        store.save(tokens('new'))
        yield json.dumps({'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call',
            'params': {'name': 'account', 'arguments': {}}}) + '\n'

    output = io.StringIO()
    server.serve(lines(), output)
    responses = [json.loads(line) for line in output.getvalue().splitlines()]
    assert [r['id'] for r in responses] == [1, 2, 3]
    first = json.loads(responses[1]['result']['content'][0]['text'])
    last = json.loads(responses[2]['result']['content'][0]['text'])
    assert first.get('signed_in') is False or first.get('error') == 'not_signed_in'
    assert last['auth_kind'] == 'clerk_oauth'
    assert 'synthetic-access-' not in output.getvalue()
    assert 'synthetic-refresh-' not in output.getvalue()


def test_logout_in_flight_does_not_delete_a_later_external_login():
    store = Store(tokens('logout'))
    replacement = tokens('later-login')
    transport, _ = oauth_server()
    base_handler = transport.handler

    def handler(request):
        if request.url.path == '/oauth/token/revoke':
            store.save(replacement)
        return base_handler(request)

    session = ClerkSession(store, transport=httpx.MockTransport(handler))
    assert session.revoke_and_clear()
    assert store.load() == replacement
    assert session.token() == replacement.access_token


def test_relogin_invalidates_remote_session_view_and_bridge_profile(tmp_path, monkeypatch):
    store = Store(tokens('old'))
    credential, _ = failed_session(store)
    seen = []

    def remote_api(request):
        body = json.loads(request.content)
        renewed = request.headers['Authorization'] == 'Bearer synthetic-access-new'
        seen.append((body['method'], renewed, request.headers.get('mcp-session-id')))
        if body['method'] == 'notifications/initialized':
            return httpx.Response(202)
        if body['method'] == 'initialize':
            result = {'protocolVersion': '2025-06-18', 'capabilities': {},
                      'serverInfo': {'name': 'synthetic', 'version': '1'}}
            return httpx.Response(200, headers={'mcp-session-id': 'new-session' if renewed else 'old-session'},
                json={'jsonrpc': '2.0', 'id': body['id'], 'result': result})
        result = {'content': [], 'structuredContent': {'data': {
            'view_mode': 'strict' if renewed else 'default',
            'view_mode_grant': 'strict' if renewed else 'default'}}}
        return httpx.Response(200, json={'jsonrpc': '2.0', 'id': body['id'], 'result': result})

    def rest_api(request):
        renewed = request.headers['Authorization'] == 'Bearer synthetic-access-new'
        return httpx.Response(200, json={'success': True, 'data': {
            'principal': {'kind': 'clerk_oauth'},
            'job_types': ['validate'] if renewed else ['convert', 'validate']}})

    monkeypatch.setattr(update, 'status', lambda: {'latest': None, 'update_available': None})
    remote = RemoteMCP('https://api.netconverter.ai/mcp/v1/', credential,
                       transport=httpx.MockTransport(remote_api))
    bridge = Bridge(tmp_path, 'https://api.netconverter.ai/external/v1', credential, remote,
        transport=httpx.MockTransport(rest_api), credential_source='clerk_session')
    try:
        first = bridge.account()
        assert first['view_mode'] == 'default'
        assert bridge.profile()[1] == frozenset({'convert', 'validate'})
        assert remote.session_id == 'old-session'
        assert credential.refresh() is False  # existing credential is invalidated
        store.save(tokens('new'))
        second = bridge.account()
        assert bridge.profile()[1] == frozenset({'validate'})
        assert second['view_mode'] == second['view_mode_grant'] == 'strict'
        assert remote.session_id == 'new-session'
        new_initializations = [r for r in seen if r[0] == 'initialize' and r[1]]
        assert new_initializations == [('initialize', True, None)]
    finally:
        remote.close()


def test_old_confirmation_cannot_authorize_remote_write_after_relogin(tmp_path):
    store = Store(tokens('old'))
    credential, _ = failed_session(store)
    upstream = RemoteServer(require_token='synthetic-access-old', tools=('get_account', 'submit_conversion'))
    remote = RemoteMCP('https://api.netconverter.ai/mcp/v1/', credential,
                       transport=httpx.MockTransport(upstream))
    bridge = Bridge(tmp_path, 'https://api.netconverter.ai/external/v1', credential, remote,
        transport=httpx.MockTransport(AccountServer()), credential_source='clerk_session')
    bridge.confirm_apply = lambda details: 'client_declined'
    args = {'job_id': 'psc_0123456789ab', 'revision': 2}
    try:
        first = bridge.call('submit_conversion', args)
        pending = json.loads(first['content'][0]['text'])
        assert pending['error'] == 'confirmation_required'
        assert credential.refresh() is False
        store.save(tokens('new'))
        upstream.require_token = 'synthetic-access-new'
        second = bridge.call('submit_conversion', {**args, 'confirm_token': pending['confirm_token']})
        assert json.loads(second['content'][0]['text'])['error'] == 'invalid_confirm_token'
        actual = [json.loads(r.content) for r in upstream.requests]
        assert not [r for r in actual if r.get('params', {}).get('name') == 'submit_conversion']
    finally:
        remote.close()


@pytest.mark.parametrize('store_error', [KeyringLocked(), CredentialStoreError('synthetic-private-store-detail')])
def test_locked_or_failed_store_has_safe_mcp_error_and_can_retry(tmp_path, monkeypatch, store_error):
    store = Store(tokens('old', expired=True))
    credential, _ = failed_session(store)
    invalidate(credential)
    original_load = store.load
    store.load = lambda: (_ for _ in ()).throw(store_error)
    api = AccountServer({'principal': {'kind': 'clerk_oauth'}}, {'job_types': ['validate']})
    monkeypatch.setattr(update, 'status', lambda: {'latest': None, 'update_available': None})
    bridge = Bridge(tmp_path, 'https://api.netconverter.ai/external/v1', credential,
        transport=httpx.MockTransport(api), credential_source='clerk_session')
    response, payload = rpc_account(StdioServer(bridge), 1)
    assert payload['error'] == 'not_signed_in'
    assert 'credential store' in payload['message']
    assert 'synthetic-private-store-detail' not in json.dumps(response)
    assert not api.requests
    store.load = original_load
    store.save(tokens('new'))
    _, recovered = rpc_account(StdioServer(bridge), 2)
    assert recovered['auth_kind'] == 'clerk_oauth'


def test_logout_after_invalidation_rejects_new_store_record_when_clear_fails():
    store = Store(tokens('revoked', expired=True))
    session, _ = failed_session(store)
    invalidate(session)
    # Logout was requested after another process logged in, before token() loaded it.
    replacement = tokens('new-before-logout')
    store.save(replacement)
    store.clear_works = False
    assert session.revoke_and_clear() is False
    assert store.load() == replacement  # failed removal cannot silently authenticate
    invalidate(session)
    assert session.refresh() is False
