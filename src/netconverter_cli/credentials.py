"""Credentials never enter workspace files or model messages."""

import getpass
import os
import sys

import keyring

SERVICE = "NetConverter Terminal"
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
        backend = keyring.get_keyring()
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
    backend = keyring.get_keyring()
    if backend.__class__.__module__ not in _OS_BACKENDS:
        return None
    return backend


def keyring_available() -> bool:
    try:
        return _os_backend() is not None
    except Exception:
        return False


def get_secret(name: str, *, prompt: bool = True) -> str:
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
            return (
                getpass.getpass(f"{name} API key (hidden, memory only): ").strip()
                if prompt
                else ""
            )
        value = backend.get_password(SERVICE, name)
    except Exception:
        value = None
    if value:
        return value
    if not prompt:
        return ""
    return getpass.getpass(f"{name} API key (hidden, memory only): ").strip()


def save_secret(name: str, value: str) -> bool:
    try:
        backend = _os_backend()
        if backend is None:
            return False
        backend.set_password(SERVICE, name, value)
        return True
    except Exception:
        return False


def load_secret(name: str) -> str:
    """Read a stored secret without prompting and without environment overrides."""
    try:
        backend = _os_backend()
        if backend is None:
            return ""
        return backend.get_password(SERVICE, name) or ""
    except Exception:
        return ""


def delete_secret(name: str) -> bool:
    """Remove a stored secret; True when nothing remains stored under ``name``."""
    try:
        backend = _os_backend()
        if backend is None:
            return False
        if backend.get_password(SERVICE, name) is None:
            return True
        backend.delete_password(SERVICE, name)
        return True
    except Exception:
        return False
