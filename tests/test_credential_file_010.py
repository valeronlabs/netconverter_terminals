"""#10: an encrypted-file credential store for headless machines (no OS keyring).

Owner decision (2026-10-22): device-code sign-in plus an encrypted-file store;
a keyring alone isn't enough. These tests prove the on-disk format (no secret in
the file's bytes, mode 0600, authenticated encryption), the store selection
(explicit `file`, automatic only when the OS keyring is unavailable) and the
messages. Surviving a real reboot on a headless box is a tester run; here a
"new process" is simulated by dropping every in-memory cache.
"""

import json
import os

import httpx
import keyring
import pytest

from netconverter_cli import clerk, cli, credential_file, credentials
from netconverter_cli.clerk import TokenSet, TokenStore

PASSPHRASE = "synthetic passphrase for tests"
TOKEN = "eyJSYNTHETIC.ACCESS.TOKEN-0123456789"
posix_only = pytest.mark.skipif(os.name == "nt", reason="POSIX file modes")


class MemoryKeyring:
    def __init__(self):
        self.items = {}

    def get_password(self, service, name):
        return self.items.get((service, name))

    def set_password(self, service, name, value):
        self.items[(service, name)] = value

    def delete_password(self, service, name):
        self.items.pop((service, name), None)


MemoryKeyring.__module__ = "keyring.backends.SecretService"


class FailKeyring(MemoryKeyring):
    pass


FailKeyring.__module__ = "keyring.backends.fail"


@pytest.fixture
def headless(monkeypatch, tmp_path):
    """No OS keyring (keyring's fail backend), a passphrase in the environment."""
    monkeypatch.setattr(keyring, "get_keyring", lambda: FailKeyring())
    monkeypatch.setattr(credentials, "session_bus_fallback", lambda *a, **k: None)
    monkeypatch.setattr(credentials, "_locked_at", None, raising=False)
    monkeypatch.setenv("NETCONVERTER_CREDENTIAL_PASSPHRASE", PASSPHRASE)
    monkeypatch.delenv("NETCONVERTER_CREDENTIAL_PASSPHRASE_FILE", raising=False)
    monkeypatch.delenv("NETCONVERTER_CREDENTIAL_STORE", raising=False)
    monkeypatch.delenv("NETCONVERTER_CREDENTIAL_FILE", raising=False)
    monkeypatch.delenv("NETCONVERTER_API_KEY", raising=False)
    monkeypatch.setattr(credential_file, "can_prompt", lambda: False)
    monkeypatch.setattr(credential_file, "SCRYPT_N", 2 ** 12)  # fast tests; the file records its own cost
    credential_file.forget_keys()
    yield credential_file.default_path()
    credential_file.forget_keys()


def new_process():
    credential_file.forget_keys()


# -- on-disk format --------------------------------------------------------------


@posix_only
def test_file_holds_no_plaintext_secret_and_is_owner_only(headless):
    assert credentials.save_secret("clerk:abc:access", TOKEN)
    assert credentials.save_secret("server:api.example.test", "nck_SYNTHETIC_KEY_42")
    raw = headless.read_bytes()
    for needle in (TOKEN, "nck_SYNTHETIC_KEY_42", "clerk:abc", "server:api", PASSPHRASE):
        assert needle.encode() not in raw
    assert oct(headless.stat().st_mode & 0o777) == "0o600"
    assert oct(headless.parent.stat().st_mode & 0o777) == "0o700"
    document = json.loads(raw)
    assert document["format"] == "netconverter-credentials" and document["version"] == 1
    assert document["cipher"] == "AES-256-GCM" and document["kdf"]["name"] == "scrypt"
    assert not list(headless.parent.glob(".nc-cred-*"))  # no temporary file left behind


def test_a_new_process_reads_it_back_with_the_passphrase(headless):
    assert credentials.save_secret("clerk:abc:access", TOKEN)
    new_process()
    assert credentials.load_secret("clerk:abc:access") == TOKEN
    assert credentials.get_secret("clerk:abc:access", prompt=False) == TOKEN


def test_wrong_passphrase_reads_nothing_and_says_why(headless, monkeypatch, capsys):
    assert credentials.save_secret("clerk:abc:access", TOKEN)
    new_process()
    monkeypatch.setenv("NETCONVERTER_CREDENTIAL_PASSPHRASE", "not the right passphrase")
    assert credentials.load_secret("clerk:abc:access") == ""
    assert "passphrase" in capsys.readouterr().err.lower()
    with pytest.raises(credential_file.WrongPassphrase):
        credential_file.EncryptedFileStore(headless).get("clerk:abc:access")


def test_tampered_file_is_refused(headless):
    assert credentials.save_secret("clerk:abc:access", TOKEN)
    document = json.loads(headless.read_text())
    document["kdf"]["n"] = 2 ** 11  # header is authenticated with the ciphertext
    headless.write_text(json.dumps(document))
    new_process()
    with pytest.raises(credential_file.FileStoreError):
        credential_file.EncryptedFileStore(headless).get("clerk:abc:access")


def test_no_passphrase_means_no_write_and_a_clear_reason(headless, monkeypatch, capsys):
    monkeypatch.delenv("NETCONVERTER_CREDENTIAL_PASSPHRASE")
    assert not credentials.save_secret("clerk:abc:access", TOKEN)
    assert not headless.exists()
    assert "NETCONVERTER_CREDENTIAL_PASSPHRASE" in capsys.readouterr().err


def test_short_passphrase_is_refused_when_creating(headless, monkeypatch):
    monkeypatch.setenv("NETCONVERTER_CREDENTIAL_PASSPHRASE", "short")
    with pytest.raises(credential_file.PassphraseUnavailable, match="at least"):
        credential_file.EncryptedFileStore(headless).set("x", "y")
    assert not headless.exists()


def test_passphrase_file_for_containers(headless, monkeypatch, tmp_path):
    secret = tmp_path / "passphrase"
    secret.write_text(PASSPHRASE + "\n")
    monkeypatch.delenv("NETCONVERTER_CREDENTIAL_PASSPHRASE")
    monkeypatch.setenv("NETCONVERTER_CREDENTIAL_PASSPHRASE_FILE", str(secret))
    assert credentials.save_secret("clerk:abc:access", TOKEN)
    new_process()
    monkeypatch.delenv("NETCONVERTER_CREDENTIAL_PASSPHRASE_FILE")
    monkeypatch.setenv("NETCONVERTER_CREDENTIAL_PASSPHRASE", PASSPHRASE)  # same passphrase, other source
    assert credentials.load_secret("clerk:abc:access") == TOKEN


def test_interactive_prompt_asks_twice_when_creating(headless, monkeypatch):
    monkeypatch.delenv("NETCONVERTER_CREDENTIAL_PASSPHRASE")
    monkeypatch.setattr(credential_file, "can_prompt", lambda: True)
    answers = iter([PASSPHRASE, PASSPHRASE])
    prompts = []
    monkeypatch.setattr(credential_file.getpass, "getpass", lambda text: prompts.append(text) or next(answers))
    assert credentials.save_secret("clerk:abc:access", TOKEN)
    assert len(prompts) == 2 and "again" in prompts[1].lower()


def test_delete_removes_the_entry_and_an_empty_file(headless):
    assert credentials.save_secret("a", "1") and credentials.save_secret("b", "2")
    assert credentials.delete_secret("a") and credentials.load_secret("a") == ""
    assert credentials.load_secret("b") == "2"
    assert credentials.delete_secret("b")
    assert not headless.exists()


# -- which store -----------------------------------------------------------------


def test_automatic_only_when_the_os_keyring_is_unavailable(headless, monkeypatch):
    assert credentials.store_in_use() == "file"
    assert "encrypted file" in credentials.store_label()
    vault = MemoryKeyring()
    monkeypatch.setattr(keyring, "get_keyring", lambda: vault)
    assert credentials.store_in_use() == "keyring"
    assert credentials.save_secret("clerk:abc:access", TOKEN)
    assert vault.items and not headless.exists()


def test_explicit_file_store_wins_over_a_working_keyring(headless, monkeypatch):
    vault = MemoryKeyring()
    monkeypatch.setattr(keyring, "get_keyring", lambda: vault)
    monkeypatch.setenv("NETCONVERTER_CREDENTIAL_STORE", "file")
    assert credentials.save_secret("clerk:abc:access", TOKEN)
    assert headless.exists() and not vault.items
    monkeypatch.delenv("NETCONVERTER_CREDENTIAL_STORE")  # auto still finds it in the file
    new_process()
    assert credentials.load_secret("clerk:abc:access") == TOKEN


def test_explicit_keyring_store_never_writes_a_file(headless, monkeypatch):
    monkeypatch.setenv("NETCONVERTER_CREDENTIAL_STORE", "keyring")
    assert not credentials.save_secret("clerk:abc:access", TOKEN)
    assert credentials.store_in_use() is None
    assert not headless.exists()


def test_credential_file_location_can_be_chosen(headless, monkeypatch, tmp_path):
    target = tmp_path / "elsewhere" / "creds.enc"
    monkeypatch.setenv("NETCONVERTER_CREDENTIAL_FILE", str(target))
    assert credentials.save_secret("a", "1")
    assert target.exists() and not headless.exists()


def test_locked_file_is_named_as_the_problem(headless, monkeypatch):
    assert credentials.save_secret("clerk:abc:access", TOKEN)
    new_process()
    monkeypatch.delenv("NETCONVERTER_CREDENTIAL_PASSPHRASE")
    problem = credentials.keyring_problem()
    assert "NETCONVERTER_CREDENTIAL_PASSPHRASE" in problem and str(headless) in problem
    monkeypatch.setenv("NETCONVERTER_CREDENTIAL_PASSPHRASE", PASSPHRASE)
    assert credentials.keyring_problem() == ""  # the file store answers


# -- sign-in and the CLI ----------------------------------------------------------


def test_clerk_tokens_go_to_the_file_on_a_headless_box(headless):
    store = TokenStore()
    assert store.save(TokenSet(TOKEN, "REFRESH_SYNTHETIC", 1234.0, "openid"))
    raw = headless.read_bytes()
    assert TOKEN.encode() not in raw and b"REFRESH_SYNTHETIC" not in raw
    new_process()
    loaded = TokenStore().load()
    assert (loaded.access_token, loaded.refresh_token) == (TOKEN, "REFRESH_SYNTHETIC")
    assert store.clear() and not headless.exists()


def test_device_login_without_keyring_saves_to_the_file(headless, monkeypatch):
    discovery = {"issuer": clerk.ISSUER, "authorization_endpoint": clerk.ISSUER + "/oauth/authorize",
                 "token_endpoint": clerk.ISSUER + "/oauth/token",
                 "device_authorization_endpoint": clerk.ISSUER + "/oauth/device_authorization",
                 "grant_types_supported": ["authorization_code", "refresh_token", clerk.DEVICE_GRANT],
                 "code_challenge_methods_supported": ["S256"]}

    def handler(request):
        if request.url.path == "/.well-known/oauth-authorization-server":
            return httpx.Response(200, json=discovery)
        if request.url.path == "/oauth/device_authorization":
            return httpx.Response(200, json={"device_code": "DC", "user_code": "ABCD",
                                             "verification_uri": clerk.ISSUER + "/device", "interval": 1})
        if request.url.path == "/oauth/token":
            return httpx.Response(200, json={"access_token": TOKEN, "refresh_token": "RT", "expires_in": 3600})
        return httpx.Response(404, json={})

    notes = []
    original = clerk.device_login
    monkeypatch.setattr(clerk, "device_login",
                        lambda http, disc, notify: original(http, disc, notify=notify, sleep=lambda _: None))
    clerk.login(device=True, transport=httpx.MockTransport(handler), notify=notes.append)
    assert any("encrypted file" in note for note in notes)
    new_process()
    assert TokenStore().load().access_token == TOKEN


def test_login_store_flag_and_whoami_name_the_store(headless, monkeypatch, capsys, tmp_path):
    vault = MemoryKeyring()
    monkeypatch.setattr(keyring, "get_keyring", lambda: vault)
    monkeypatch.setattr(cli.getpass, "getpass", lambda text: "nck_SYNTHETIC_KEY_42")
    monkeypatch.setattr(cli, "detect_profile", lambda key, server: ("external", None))  # no network
    cli.main(["--workspace", str(tmp_path), "login", "--store", "file"])
    out = json.loads(capsys.readouterr().out)
    assert out["credential_storage"].startswith("encrypted file")
    assert not vault.items and headless.exists()
    assert b"nck_SYNTHETIC_KEY_42" not in headless.read_bytes()
    cli.main(["--workspace", str(tmp_path), "whoami"])
    who = json.loads(capsys.readouterr().out)
    assert who["api_key_stored"] is True
    assert who["credential_store"].startswith("encrypted file")


def test_docs_describe_the_store_and_its_threat_model():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    privacy = (root / "docs" / "PRIVACY.md").read_text(encoding="utf-8")
    commands = (root / "docs" / "COMMANDS.md").read_text(encoding="utf-8")
    for text in (privacy, commands):
        assert "NETCONVERTER_CREDENTIAL_STORE" in text and "NETCONVERTER_CREDENTIAL_PASSPHRASE" in text
    assert "does not protect" in privacy.lower()
    assert "--store" in commands
