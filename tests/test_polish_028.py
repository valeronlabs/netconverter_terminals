"""devnexthop#28 (a), (b), (d): /ls title, /help footer, unescaped one-shot JSON.

(c), reasons cut mid-word, is the server's report truncation (aws-netconverter.ai).
"""

from pathlib import Path

import httpx
import pytest
from rich.console import Console

from netconverter_cli import cli
from netconverter_cli.api import ExternalClient, StaticCredential
from netconverter_cli.presentation import folder_view, help_view

SERVER = "https://api.example/external/v1"


def test_ls_title_uses_the_home_form(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    listing = {"folder": str(tmp_path / "migrations"), "entries": [], "total": 0, "inside_workspace": True}
    assert folder_view(listing).title.plain == "~/migrations"


def test_help_card_footer_is_not_the_picker_hint():
    console = Console(width=120, record=True)
    console.print(help_view())
    text = console.export_text()
    assert "Type a command · Esc close · Ctrl+Q quit" in text
    assert "choose" not in text.splitlines()[-2] and "Esc cancel" not in text


def test_one_shot_json_keeps_unicode(tmp_path, monkeypatch, capsys):
    def handler(request):
        path = request.url.path.removeprefix("/external/v1/")
        data = {"job_types": ["convert"]} if path == "me" else {
            "vendors": [{"code": "fortinet", "name": "Fortinet → FortiGate", "device_type": "firewall",
                         "roles": ["source"]}], "job_types": ["convert"]}
        return httpx.Response(200, json={"success": True, "data": data})

    client = ExternalClient(StaticCredential("nck_synthetic"), SERVER, transport=httpx.MockTransport(handler))
    monkeypatch.setattr(cli, "open_client", lambda credential, url: (client, "external"))
    monkeypatch.setattr(cli, "rest_credential", lambda *a, **k: "nck_synthetic")
    cli.main(["--workspace", str(tmp_path), "--server", SERVER, "capabilities"])
    out = capsys.readouterr().out
    assert "Fortinet → FortiGate" in out and "\\u2192" not in out


def test_unicode_json_on_a_legacy_code_page_does_not_crash(tmp_path, monkeypatch):
    import io
    import sys

    stream = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
    monkeypatch.setattr(sys, "stdout", stream)
    monkeypatch.setattr(cli, "load_secret", lambda name: "")
    monkeypatch.setattr(cli, "_clerk_session", lambda: None)
    monkeypatch.setattr(cli, "whoami", lambda args: print('{"note": "wan1 → ethernet1/1"}'))
    cli.main(["whoami"])
    stream.flush()
    assert b"\\u2192" in stream.buffer.getvalue()
