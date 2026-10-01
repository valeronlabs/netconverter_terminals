"""Credentials never enter workspace files or model messages."""

import getpass
import os

import keyring


def get_secret(name: str, *, prompt: bool = True) -> str:
    value = os.environ.get(
        "NETCONVERTER_API_KEY"
        if name == "server" or name.startswith("server:")
        else f"NETCONVERTER_{name.upper()}_API_KEY"
    )
    if value:
        return value
    try:
        backend = keyring.get_keyring()
        if backend.__class__.__module__ not in {
            "keyring.backends.macOS",
            "keyring.backends.Windows",
            "keyring.backends.SecretService",
        }:
            return (
                getpass.getpass(f"{name} API key (hidden, memory only): ").strip()
                if prompt
                else ""
            )
        value = backend.get_password("NetConverter Terminal", name)
    except Exception:
        value = None
    if value:
        return value
    if not prompt:
        return ""
    return getpass.getpass(f"{name} API key (hidden, memory only): ").strip()


def save_secret(name: str, value: str) -> bool:
    try:
        # Refuse third-party plaintext backends; no fallback secrets file.
        backend = keyring.get_keyring()
        if backend.__class__.__module__ not in {
            "keyring.backends.macOS",
            "keyring.backends.Windows",
            "keyring.backends.SecretService",
        }:
            return False
        backend.set_password("NetConverter Terminal", name, value)
        return True
    except Exception:
        return False
