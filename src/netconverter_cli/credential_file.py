"""An encrypted credential file for machines without an OS keyring (#10).

Owner decision (2026-10-22): headless sign-in is device-code login plus an
encrypted-file store, so a sign-in on an SSH host or in a container survives a
reboot where no Secret Service runs. ``credentials.py`` chooses this store
explicitly (``NETCONVERTER_CREDENTIAL_STORE=file``, ``login --store file``) or
automatically when the OS keyring is unavailable.

Format: one JSON document; nothing in it is a secret or names one.

* key: scrypt (RFC 7914) over the user's passphrase with a random 16-byte salt;
  the cost parameters are stored so a later version can raise them;
* cipher: AES-256-GCM from ``cryptography`` (pyca), a fresh 12-byte random
  nonce on every write; the header (format, version, cipher, kdf) is the
  associated data, so a tampered header or ciphertext is refused;
* plaintext: ``{"entries": {name: value}}``, so entry names are encrypted too.

The passphrase comes from ``NETCONVERTER_CREDENTIAL_PASSPHRASE``, the file
named by ``NETCONVERTER_CREDENTIAL_PASSPHRASE_FILE`` (Docker/Kubernetes
secrets, systemd credentials), or a hidden prompt on a terminal. It is never
written anywhere; the derived key is kept in memory for this process only.
The file is written atomically with mode 0600 in a 0700 folder.

What this protects against, and what it doesn't, is in docs/PRIVACY.md.
"""

from __future__ import annotations

import base64
import getpass
import json
import os
import secrets
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

FORMAT = "netconverter-credentials"
VERSION = 1
CIPHER = "AES-256-GCM"
PASSPHRASE_ENV = "NETCONVERTER_CREDENTIAL_PASSPHRASE"
PASSPHRASE_FILE_ENV = "NETCONVERTER_CREDENTIAL_PASSPHRASE_FILE"
FILE_ENV = "NETCONVERTER_CREDENTIAL_FILE"
FILE_NAME = "credentials.enc"
MIN_PASSPHRASE = 12
# scrypt cost for new files: N=2^15, r=8, p=1 (about 32 MiB and a fraction of a
# second, once per process). A file records its own parameters.
SCRYPT_N = 2 ** 15
SCRYPT_R = 8
SCRYPT_P = 1
_MAX_SCRYPT_N = 2 ** 20  # refuse a file that asks for an absurd cost
_MAX_BYTES = 1024 * 1024

# Derived keys, by (file, salt): the passphrase is asked for once per process.
_KEYS: dict[tuple[str, str], bytes] = {}
# A new file's KDF parameters, chosen when its passphrase was checked (prepare).
_NEW_KDF: dict[str, dict] = {}


class FileStoreError(RuntimeError):
    """The encrypted credential file cannot be used; the message is safe to show."""


class PassphraseUnavailable(FileStoreError):
    """No passphrase in the environment and no terminal to ask on."""


class WrongPassphrase(FileStoreError):
    """The passphrase does not open the file (or the file was altered)."""


def default_path() -> Path:
    override = os.getenv(FILE_ENV)
    if override:
        return Path(override).expanduser()
    from .license import config_dir

    return config_dir() / FILE_NAME


def can_prompt() -> bool:
    """Ask for the passphrase only on a real terminal (never inside an MCP bridge's pipe)."""
    try:
        return sys.stdin.isatty() and sys.stderr.isatty()
    except (AttributeError, ValueError):
        return False


def forget_keys() -> None:
    """Drop every derived key held in memory (tests; the end of a process does the same)."""
    _KEYS.clear()
    _NEW_KDF.clear()


def passphrase_hint() -> str:
    return (f"set {PASSPHRASE_ENV} (or {PASSPHRASE_FILE_ENV} naming a file that holds it) "
            "in this process's environment")


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _unb64(text) -> bytes:
    if not isinstance(text, str):
        raise ValueError("not base64 text")
    return base64.b64decode(text.encode("ascii"), validate=True)


class EncryptedFileStore:
    label_prefix = "encrypted file"

    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path is not None else default_path()
        self._id = os.path.abspath(self.path)

    @property
    def label(self) -> str:
        return f"{self.label_prefix} {self.path}"

    def exists(self) -> bool:
        return self.path.is_file()

    # -- passphrase and key --------------------------------------------------

    def _passphrase(self, *, creating: bool) -> str:
        value = os.environ.get(PASSPHRASE_ENV)
        source = PASSPHRASE_ENV
        if not value and os.environ.get(PASSPHRASE_FILE_ENV):
            source = PASSPHRASE_FILE_ENV
            try:
                value = Path(os.environ[PASSPHRASE_FILE_ENV]).expanduser().read_text(encoding="utf-8")
            except OSError as exc:
                raise PassphraseUnavailable(
                    f"Cannot read the passphrase file named by {PASSPHRASE_FILE_ENV} "
                    f"({type(exc).__name__})") from None
            value = value.rstrip("\r\n")
        if not value and can_prompt():
            source = "prompt"
            what = "a new passphrase for" if creating else "the passphrase for"
            value = getpass.getpass(f"Enter {what} the NetConverter credential file {self.path} "
                                    "(hidden): ")
            if creating and value and getpass.getpass("Enter it again (hidden): ") != value:
                raise PassphraseUnavailable("The two passphrases did not match; nothing was saved.")
        if not value:
            raise PassphraseUnavailable(
                f"The NetConverter credential file {self.path} needs a passphrase: {passphrase_hint()}.")
        if creating and len(value) < MIN_PASSPHRASE:
            raise PassphraseUnavailable(
                f"The credential-file passphrase must be at least {MIN_PASSPHRASE} characters "
                f"(from {source}); nothing was saved.")
        return value

    def _key(self, kdf: dict, *, creating: bool) -> bytes:
        cache = (self._id, kdf["salt"])
        if cache in _KEYS:
            return _KEYS[cache]
        derived = Scrypt(salt=_unb64(kdf["salt"]), length=32, n=int(kdf["n"]), r=int(kdf["r"]),
                         p=int(kdf["p"])).derive(self._passphrase(creating=creating).encode("utf-8"))
        _KEYS[cache] = derived
        return derived

    # -- file IO ---------------------------------------------------------------

    @staticmethod
    def _header(document: dict) -> bytes:
        header = {k: document[k] for k in ("format", "version", "cipher", "kdf")}
        return json.dumps(header, sort_keys=True, separators=(",", ":")).encode("utf-8")

    def _read_document(self) -> dict | None:
        try:
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            fd = os.open(self.path, flags)
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise FileStoreError(f"Cannot open the credential file {self.path} ({type(exc).__name__})") from None
        with os.fdopen(fd, "rb") as stream:
            raw = stream.read(_MAX_BYTES + 1)
        try:
            document = json.loads(raw)
            kdf = document["kdf"]
            valid = (len(raw) <= _MAX_BYTES and document["format"] == FORMAT and document["version"] == VERSION
                     and document["cipher"] == CIPHER and kdf["name"] == "scrypt"
                     and 2 <= int(kdf["n"]) <= _MAX_SCRYPT_N and 1 <= int(kdf["r"]) <= 32
                     and 1 <= int(kdf["p"]) <= 16 and len(_unb64(kdf["salt"])) >= 16
                     and len(_unb64(document["nonce"])) == 12)
        except (ValueError, KeyError, TypeError):
            valid = False
        if not valid:
            raise FileStoreError(f"{self.path} is not a NetConverter credential file this version can read.")
        return document

    def _load(self) -> tuple[dict | None, dict]:
        """(document, entries); (None, {}) when there is no file yet."""
        document = self._read_document()
        if document is None:
            return None, {}
        key = self._key(document["kdf"], creating=False)
        try:
            plain = AESGCM(key).decrypt(_unb64(document["nonce"]), _unb64(document["ciphertext"]),
                                        self._header(document))
        except (InvalidTag, ValueError):
            _KEYS.pop((self._id, document["kdf"]["salt"]), None)
            raise WrongPassphrase(
                f"The passphrase does not open the credential file {self.path} "
                "(wrong passphrase, or the file was changed).") from None
        entries = json.loads(plain).get("entries")
        return document, entries if isinstance(entries, dict) else {}

    def _write(self, document: dict | None, entries: dict) -> None:
        if not entries:
            self.path.unlink(missing_ok=True)
            return
        if document is None:  # a new file: new salt (or the one prepare chose), current cost
            kdf = _NEW_KDF.pop(self._id, None) or self._new_kdf()
            key = self._key(kdf, creating=True)
        else:
            kdf = document["kdf"]
            key = self._key(kdf, creating=False)
        out = {"format": FORMAT, "version": VERSION, "cipher": CIPHER, "kdf": kdf}
        nonce = secrets.token_bytes(12)
        ciphertext = AESGCM(key).encrypt(nonce, json.dumps({"entries": entries}).encode("utf-8"),
                                         self._header(out))
        out.update(nonce=_b64(nonce), ciphertext=_b64(ciphertext))
        self._replace(json.dumps(out, indent=1).encode("utf-8") + b"\n")

    def _replace(self, data: bytes) -> None:
        folder = self.path.parent
        folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix=".nc-cred-", dir=folder)  # created 0600
        try:
            if os.name != "nt":
                os.fchmod(fd, 0o600)
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, self.path)
        finally:
            Path(name).unlink(missing_ok=True)

    @contextmanager
    def _locked(self):
        """Serialize read-modify-write between processes (POSIX); the replace itself is atomic."""
        try:
            import fcntl
        except ImportError:  # Windows: the atomic replace alone
            yield
            return
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd = os.open(str(self.path) + ".lock", os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    # -- the store interface ---------------------------------------------------

    def unlockable(self) -> bool:
        """The file exists and this process can open it, without asking anyone."""
        if not self.exists():
            return False
        if os.environ.get(PASSPHRASE_ENV) or os.environ.get(PASSPHRASE_FILE_ENV):
            try:
                self._load()
                return True
            except FileStoreError:
                return False
        document = self._read_document()
        return bool(document) and (self._id, document["kdf"]["salt"]) in _KEYS

    @staticmethod
    def _new_kdf() -> dict:
        return {"name": "scrypt", "n": SCRYPT_N, "r": SCRYPT_R, "p": SCRYPT_P,
                "salt": _b64(secrets.token_bytes(16))}

    def prepare(self) -> None:
        """Ask for (or check) the passphrase now, before a sign-in that will need it."""
        document, _ = self._load()
        if document is None and self._id not in _NEW_KDF:
            kdf = self._new_kdf()
            self._key(kdf, creating=True)
            _NEW_KDF[self._id] = kdf  # the first write uses this salt and its derived key

    def get(self, name: str) -> str | None:
        _, entries = self._load()
        value = entries.get(name)
        return value if isinstance(value, str) else None

    def set(self, name: str, value: str) -> None:
        with self._locked():
            document, entries = self._load()
            entries[name] = value
            self._write(document, entries)

    def delete(self, name: str) -> None:
        if not self.exists():
            return
        with self._locked():
            document, entries = self._load()
            if name in entries:
                entries.pop(name)
                self._write(document, entries)
