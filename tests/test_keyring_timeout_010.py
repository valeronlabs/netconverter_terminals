"""#10 (partial): a locked keyring times out with a clear message; one signed-out sentence.

No real keyring is touched: a fake OS backend blocks the way a locked Secret
Service collection does after a reboot.
"""

import threading
import time
from pathlib import Path

import pytest

from netconverter_cli import cli, credentials, errors, setup

ROOT = Path(__file__).resolve().parents[1]


class BlockingKeyring:
    """Passes the OS-backend check; every call waits until the test releases it."""

    def __init__(self):
        self.release = threading.Event()
        self.calls = 0

    def _wait(self, *args):
        self.calls += 1
        self.release.wait(30)
        return None

    get_password = set_password = delete_password = _wait


BlockingKeyring.__module__ = "keyring.backends.SecretService"


@pytest.fixture
def locked(monkeypatch):
    backend = BlockingKeyring()
    monkeypatch.setattr(credentials.keyring, "get_keyring", lambda: backend)
    monkeypatch.setattr(credentials, "session_bus_fallback", lambda *a, **k: None)
    monkeypatch.setattr(credentials, "_locked_at", None, raising=False)
    monkeypatch.delenv("NETCONVERTER_API_KEY", raising=False)
    monkeypatch.delenv("NETCONVERTER_KEYRING_TIMEOUT_S", raising=False)
    yield backend
    backend.release.set()


def test_whoami_with_a_locked_keyring_answers_within_six_seconds(locked, capsys):
    started = time.monotonic()
    with pytest.raises(SystemExit) as info:
        cli.main(["whoami"])
    elapsed = time.monotonic() - started
    assert elapsed < 6, elapsed
    assert info.value.code == errors.EXIT_AUTH
    err = capsys.readouterr().err
    assert ("Your system keyring is locked, so NetConverter can't read your sign-in. "
            "Unlock it, or sign in again with `netconverter login`.") in err


def test_after_one_timeout_later_calls_fail_fast(locked, monkeypatch):
    monkeypatch.setattr(credentials, "KEYRING_TIMEOUT_S", 0.2)
    with pytest.raises(credentials.KeyringLocked):
        credentials.get_secret("server:abc", prompt=False)
    started = time.monotonic()
    for call in (lambda: credentials.load_secret("clerk:x:access"),
                 lambda: credentials.save_secret("clerk:x:access", "t"),
                 lambda: credentials.delete_secret("clerk:x:access")):
        with pytest.raises(credentials.KeyringLocked):
            call()
    assert time.monotonic() - started < 0.2
    assert locked.calls == 1


def test_the_bridge_starts_and_says_the_keyring_is_locked(locked, monkeypatch):
    monkeypatch.setattr(credentials, "KEYRING_TIMEOUT_S", 0.2)
    monkeypatch.setattr(cli, "_clerk_session", cli._clerk_session)
    rest, remote, source, notes = cli.choose_mcp_credential("auto", "https://api.netconverter.ai/external/v1",
                                                             "https://api.netconverter.ai/mcp/v1/")
    assert (rest, remote, source) == (None, None, "none")
    assert any(errors.KEYRING_LOCKED in note for note in notes)


# -- one signed-out sentence ------------------------------------------------


def test_setup_without_a_key_prints_the_signed_out_message():
    class NoSignIn:
        def allowed(self, server):
            return False

    with pytest.raises(SystemExit) as info:
        setup.connect_credential("https://api.example/external/v1", NoSignIn(), lambda _: "", lambda _: "")
    assert str(info.value) == errors.SIGNED_OUT and info.value.code == errors.EXIT_AUTH


def test_clerk_token_without_a_sign_in_uses_the_signed_out_message():
    from netconverter_cli.clerk import ClerkError, ClerkSession

    class Empty:
        def load(self):
            return None

    with pytest.raises(ClerkError) as info:
        ClerkSession(store=Empty()).token()
    assert str(info.value) == errors.SIGNED_OUT


def test_every_signed_out_path_uses_the_one_sentence():
    """No module carries its own variant; CLI, app (401) and setup share errors.SIGNED_OUT."""
    source = "\n".join(p.read_text(encoding="utf-8") for p in (ROOT / "src" / "netconverter_cli").glob("*.py"))
    for variant in ("Not signed in;", "No NetConverter API key;", "No NetConverter credential for",
                    "NetConverter did not accept your sign-in", "A server API key is required"):
        assert variant not in source, variant
    for module in ("cli.py", "setup.py", "errors.py", "clerk.py"):
        assert "SIGNED_OUT" in (ROOT / "src" / "netconverter_cli" / module).read_text(encoding="utf-8"), module
