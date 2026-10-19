"""A NetConverter sign-in is used without an environment variable.

Reproduced on Windows 2026-10-19: after `netconverter login --clerk`, every
plain command prompted for a server API key (NETCONVERTER_AUTH unset), and
first-run setup in a new folder accepted only a key. With no key stored for a
trusted server, the sign-in is the credential; NETCONVERTER_AUTH=key|clerk
stay explicit overrides, and the workspace's connection.json never chooses.
"""
from unittest.mock import Mock

import pytest

from netconverter_cli import cli, setup

PROD = "https://api.netconverter.ai/external/v1"


class FakeSession:
    kind = "clerk"
    signed_in = True


def no_prompt(name, *, prompt=True):
    assert prompt is False, "must not prompt for an API key"
    return ""


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in ("NETCONVERTER_AUTH", "NETCONVERTER_TRUSTED_HOSTS", "NETCONVERTER_API_KEY"):
        monkeypatch.delenv(name, raising=False)


def test_signed_in_without_key_uses_the_sign_in(monkeypatch):
    session = FakeSession()
    monkeypatch.setattr(cli, "_clerk_session", lambda: session)
    monkeypatch.setattr(cli, "get_secret", no_prompt)
    assert cli.rest_credential(PROD, {}) is session


def test_stored_key_wins_over_the_sign_in(monkeypatch):
    monkeypatch.setattr(cli, "_clerk_session", lambda: FakeSession())
    monkeypatch.setattr(cli, "get_secret", lambda name, prompt=True: "nck_STORED")
    assert cli.rest_credential(PROD, {}) == "nck_STORED"


def test_untrusted_server_never_gets_the_sign_in(monkeypatch):
    monkeypatch.setattr(cli, "_clerk_session", lambda: pytest.fail("token must not be loaded"))
    monkeypatch.setattr(cli, "get_secret", no_prompt)
    monkeypatch.setattr(cli, "keyring_available", lambda: True)
    with pytest.raises(SystemExit) as exc:
        cli.rest_credential("https://evil.example/external/v1", {})
    assert "login" in str(exc.value)


def test_no_key_and_not_signed_in_says_how_to_connect(monkeypatch):
    monkeypatch.setattr(cli, "_clerk_session", lambda: None)
    monkeypatch.setattr(cli, "get_secret", no_prompt)
    monkeypatch.setattr(cli, "keyring_available", lambda: True)
    with pytest.raises(SystemExit) as exc:
        cli.rest_credential(PROD, {})
    assert "netconverter login --clerk" in str(exc.value)


def test_auth_key_override_keeps_the_key_prompt(monkeypatch):
    monkeypatch.setenv("NETCONVERTER_AUTH", "key")
    monkeypatch.setattr(cli, "_clerk_session", lambda: pytest.fail("key mode must not load the sign-in"))
    secret = Mock(return_value="nck_TYPED")
    monkeypatch.setattr(cli, "get_secret", secret)
    assert cli.rest_credential(PROD, {}) == "nck_TYPED"
    secret.assert_called_once_with(setup.account(PROD))


def test_auth_clerk_override_ignores_a_stored_key(monkeypatch):
    monkeypatch.setenv("NETCONVERTER_AUTH", "clerk")
    session = FakeSession()
    monkeypatch.setattr(cli, "_clerk_session", lambda: session)
    monkeypatch.setattr(cli, "get_secret", lambda *a, **k: pytest.fail("clerk mode must not read the key"))
    assert cli.rest_credential(PROD, {}) is session


def test_workspace_auth_setting_cannot_force_the_sign_in(monkeypatch):
    monkeypatch.setattr(cli, "_clerk_session", lambda: FakeSession())
    monkeypatch.setattr(cli, "get_secret", lambda name, prompt=True: "nck_STORED")
    assert cli.rest_credential(PROD, {"auth": "clerk"}) == "nck_STORED"


def test_capabilities_with_sign_in_and_no_env(tmp_path, monkeypatch):
    session = FakeSession()
    monkeypatch.setattr(cli, "_clerk_session", lambda: session)
    monkeypatch.setattr(cli, "get_secret", no_prompt)
    client = Mock()
    factory = Mock(return_value=(client, "external"))
    monkeypatch.setattr(cli, "open_client", factory)
    monkeypatch.setattr(cli.Controller, "capabilities", lambda self: {"vendors": ["asa"]})
    cli.main(["--workspace", str(tmp_path), "--server", PROD, "capabilities"])
    factory.assert_called_once_with(session, PROD)


# ---- first-run setup ------------------------------------------------------


class FakeSignIn:
    def __init__(self, session=None, after_login=None, allowed=True):
        self._session, self._after, self._allowed = session, after_login, allowed
        self.logins = 0

    def allowed(self, server):
        return self._allowed

    def session(self):
        return self._session

    def login(self):
        self.logins += 1
        self._session = self._after
        return self._session


def _setup_mocks(monkeypatch):
    client = Mock()
    factory = Mock(return_value=(client, "external"))
    monkeypatch.setattr(setup, "open_client", factory)
    monkeypatch.setattr(setup, "get_secret", lambda name, prompt=True: "")
    save = Mock(return_value=True)
    monkeypatch.setattr(setup, "save_secret", save)
    return client, factory, save


def test_setup_uses_an_existing_sign_in_without_asking_for_a_key(tmp_path, monkeypatch):
    client, factory, save = _setup_mocks(monkeypatch)
    session = FakeSession()
    answers = iter(["", "none"])
    c, p = setup.configure(tmp_path, ask=lambda _: next(answers),
                           secret=lambda _: pytest.fail("no key prompt when signed in"),
                           signin=FakeSignIn(session))
    assert c is client and p is None
    factory.assert_called_once_with(session, setup.DEFAULT_BASE)
    save.assert_not_called()
    assert "clerk" not in (tmp_path / ".netconverter/connection.json").read_text()


def test_setup_offers_sign_in_and_runs_it(tmp_path, monkeypatch):
    client, factory, save = _setup_mocks(monkeypatch)
    session = FakeSession()
    signin = FakeSignIn(None, after_login=session)
    answers = iter(["", "1", "none"])
    c, _ = setup.configure(tmp_path, ask=lambda _: next(answers),
                           secret=lambda _: pytest.fail("sign-in chosen; no key prompt"), signin=signin)
    assert signin.logins == 1
    factory.assert_called_once_with(session, setup.DEFAULT_BASE)


def test_setup_can_still_take_a_key(tmp_path, monkeypatch):
    client, factory, save = _setup_mocks(monkeypatch)
    signin = FakeSignIn(None)
    answers = iter(["", "2", "none"])
    setup.configure(tmp_path, ask=lambda _: next(answers), secret=lambda _: "nck_PASTED", signin=signin)
    assert signin.logins == 0
    factory.assert_called_once_with("nck_PASTED", setup.DEFAULT_BASE)
    assert save.call_args.args == (setup.account(setup.DEFAULT_BASE), "nck_PASTED")


def test_setup_never_offers_sign_in_to_an_untrusted_server(tmp_path, monkeypatch):
    client, factory, save = _setup_mocks(monkeypatch)
    signin = FakeSignIn(FakeSession(), allowed=False)
    answers = iter(["https://pilot.example/external/v1", "none"])
    setup.configure(tmp_path, ask=lambda _: next(answers), secret=lambda _: "nck_PASTED", signin=signin)
    factory.assert_called_once_with("nck_PASTED", "https://pilot.example/external/v1")


def test_plain_netconverter_in_a_new_folder_reaches_the_app_signed_in(tmp_path, monkeypatch):
    session = FakeSession()
    monkeypatch.setattr(cli, "_clerk_session", lambda: session)
    monkeypatch.setattr(setup, "get_secret", lambda name, prompt=True: "")
    monkeypatch.setattr(setup, "save_secret", Mock(return_value=True))
    client = Mock()
    factory = Mock(return_value=(client, "external"))
    monkeypatch.setattr(setup, "open_client", factory)
    answers = iter(["", "none"])
    monkeypatch.setattr("builtins.input", lambda _="": next(answers))
    monkeypatch.setattr("getpass.getpass", lambda *_a, **_k: pytest.fail("no key prompt when signed in"))
    ran = Mock()
    import netconverter_cli.tui as tui
    monkeypatch.setattr(tui, "Terminal", lambda controller: Mock(run=ran))
    cli.main(["--workspace", str(tmp_path)])
    factory.assert_called_once_with(session, PROD)
    ran.assert_called_once()
