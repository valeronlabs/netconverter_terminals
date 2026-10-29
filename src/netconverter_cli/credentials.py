"""Credentials never enter workspace files or model messages."""

import getpass
import os
import sys
import threading
import time

import keyring

from .errors import KEYRING_LOCKED

SERVICE = "NetConverter Terminal"
# A locked Secret Service collection (or a keychain waiting on a dialog) can block
# a keyring call indefinitely; whoami hung for over 30 s after a reboot (#10).
KEYRING_TIMEOUT_S = 5.0
_RETRY_LOCKED_AFTER_S = 30.0
_locked_at: float | None = None


class KeyringLocked(RuntimeError):
    """The OS credential store did not answer in time."""

    def __init__(self):
        super().__init__(KEYRING_LOCKED)


def _timeout() -> float:
    """KEYRING_TIMEOUT_S, or NETCONVERTER_KEYRING_TIMEOUT_S for a keychain that asks slowly."""
    try:
        return max(0.1, float(os.environ["NETCONVERTER_KEYRING_TIMEOUT_S"]))
    except (KeyError, ValueError):
        return KEYRING_TIMEOUT_S


def _bounded(call, *args):
    """Run one keyring call with a deadline; a call that never returns means locked.

    After one timeout, calls fail fast for a while instead of each waiting again.
    """
    global _locked_at
    if _locked_at is not None and time.monotonic() - _locked_at < _RETRY_LOCKED_AFTER_S:
        raise KeyringLocked()
    box = {}

    def target():
        try:
            box["value"] = call(*args)
        except BaseException as exc:  # noqa: BLE001 - re-raised in the caller's thread
            box["error"] = exc

    worker = threading.Thread(target=target, name="netconverter-keyring", daemon=True)
    worker.start()
    worker.join(_timeout())
    if worker.is_alive():
        _locked_at = time.monotonic()
        raise KeyringLocked()
    _locked_at = None
    if "error" in box:
        raise box["error"]
    return box.get("value")
# Only operating-system credential stores are trusted. Third-party keyring
# backends (plaintext files, encrypted-file backends with a master password on
# disk) are refused; there is no fallback secrets file.
_OS_BACKENDS = frozenset(
    {
        "keyring.backends.macOS",
        "keyring.backends.Windows",
        "keyring.backends.SecretService",
    }
)


def session_bus_fallback(environ=None, *, platform=None, uid=None, exists=os.path.exists):
    """Linux: point DBUS_SESSION_BUS_ADDRESS at the user's bus socket when it is unset (#17).

    Codex, Cursor CLI and OpenClaw start stdio MCP servers with a near-empty
    environment, and jeepney (keyring → Secret Service) reads only that
    variable, so the sign-in in the OS keyring was invisible. Tries
    ``$XDG_RUNTIME_DIR/bus``, then ``/run/user/<uid>/bus``; returns the socket
    path it chose, else None. Must run before keyring picks its backend.
    """
    environ = os.environ if environ is None else environ
    platform = sys.platform if platform is None else platform
    if not platform.startswith("linux") or environ.get("DBUS_SESSION_BUS_ADDRESS"):
        return None
    candidates = []
    runtime = environ.get("XDG_RUNTIME_DIR")
    if runtime:
        candidates.append(f"{runtime.rstrip('/')}/bus")
    if uid is None:
        uid = getattr(os, "getuid", lambda: None)()
    if uid is not None:
        candidates.append(f"/run/user/{uid}/bus")
    for path in dict.fromkeys(candidates):  # in order, without a duplicate
        if exists(path):
            environ["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path={path}"
            return path
    return None


def keyring_problem() -> str:
    """Why no OS credential store is reachable; "" when one is (#17).

    Written for the person reading an AI client's tool error: it names the
    missing D-Bus bus and the keyring backend in use, never a secret.
    """
    session_bus_fallback()
    try:
        backend = _bounded(keyring.get_keyring)
    except KeyringLocked:
        return KEYRING_LOCKED
    except Exception as exc:  # noqa: BLE001 - any keyring failure is the answer
        return f"the keyring library failed ({type(exc).__name__})"
    if backend.__class__.__module__ in _OS_BACKENDS:
        return ""
    name = f"{backend.__class__.__module__}.{backend.__class__.__name__}"
    if sys.platform.startswith("linux"):
        if not os.environ.get("DBUS_SESSION_BUS_ADDRESS"):
            return ("no D-Bus session bus: DBUS_SESSION_BUS_ADDRESS is not set and no "
                    "/run/user/<uid>/bus socket was found, so the Secret Service keyring is "
                    f"unreachable (keyring backend: {name})")
        return f"the Secret Service keyring did not answer on the D-Bus session bus (keyring backend: {name})"
    return f"no OS credential store is available (keyring backend: {name})"


def _os_backend():
    session_bus_fallback()
    backend = _bounded(keyring.get_keyring)
    if backend.__class__.__module__ not in _OS_BACKENDS:
        return None
    return backend


def keyring_available() -> bool:
    try:
        return _os_backend() is not None
    except KeyringLocked:
        raise
    except Exception:
        return False


def _prompt_text(name: str, label: str | None) -> str:
    """The hidden-input prompt: names the host, never the internal credential-store id (#9)."""
    if name == "server" or name.startswith("server:"):
        what = f"NetConverter API key for {label}" if label else "NetConverter API key"
    else:
        what = f"{name} API key"
    return f"{what} (hidden; kept in memory for this run only): "


def get_secret(name: str, *, prompt: bool = True, label: str | None = None) -> str:
    value = os.environ.get(
        "NETCONVERTER_API_KEY"
        if name == "server" or name.startswith("server:")
        else f"NETCONVERTER_{name.upper()}_API_KEY"
    )
    if value:
        return value
    try:
        backend = _os_backend()
        if backend is None:
            return getpass.getpass(_prompt_text(name, label)).strip() if prompt else ""
        value = _bounded(backend.get_password, SERVICE, name)
    except KeyringLocked:
        raise
    except Exception:
        value = None
    if value:
        return value
    if not prompt:
        return ""
    return getpass.getpass(_prompt_text(name, label)).strip()


def save_secret(name: str, value: str) -> bool:
    try:
        backend = _os_backend()
        if backend is None:
            return False
        _bounded(backend.set_password, SERVICE, name, value)
        return True
    except KeyringLocked:
        raise
    except Exception:
        return False


def load_secret(name: str) -> str:
    """Read a stored secret without prompting and without environment overrides."""
    try:
        backend = _os_backend()
        if backend is None:
            return ""
        return _bounded(backend.get_password, SERVICE, name) or ""
    except KeyringLocked:
        raise
    except Exception:
        return ""


def delete_secret(name: str) -> bool:
    """Remove a stored secret; True when nothing remains stored under ``name``."""
    try:
        backend = _os_backend()
        if backend is None:
            return False
        if _bounded(backend.get_password, SERVICE, name) is None:
            return True
        _bounded(backend.delete_password, SERVICE, name)
        return True
    except KeyringLocked:
        raise
    except Exception:
        return False
