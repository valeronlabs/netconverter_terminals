"""Credentials never enter workspace files or model messages."""

import getpass
import os

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


def _os_backend():
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
