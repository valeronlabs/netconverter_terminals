"""`netconverter update` and the passive notice. GitHub is mocked; nothing is installed."""

import hashlib
import io
import json
import time
from types import SimpleNamespace

import httpx
import pytest

from netconverter_cli import __version__, update

TAG = "v9.8.7"
WHEEL_NAME = "netconverter_cli-9.8.7-py3-none-any.whl"
WHEEL = b"PK\x03\x04synthetic-wheel-bytes"
PREFIX = f"https://github.com/{update.REPO}/releases/download/{TAG}/"


class GitHub:
    def __init__(self, tag=TAG, wheel=WHEEL, sums=None, assets=None, redirect_host="objects.githubusercontent.com"):
        self.tag, self.wheel, self.redirect_host = tag, wheel, redirect_host
        self.sums = sums if sums is not None else f"{hashlib.sha256(WHEEL).hexdigest()}  {WHEEL_NAME}\n".encode()
        self.assets = assets if assets is not None else [
            {"name": WHEEL_NAME, "browser_download_url": PREFIX + WHEEL_NAME},
            {"name": "SHA256SUMS", "browser_download_url": PREFIX + "SHA256SUMS"},
        ]
        self.requests = []

    def __call__(self, request):
        self.requests.append(request)
        assert "authorization" not in request.headers  # never a credential
        url = str(request.url)
        if url == update.LATEST_URL:
            return httpx.Response(200, json={"tag_name": self.tag, "assets": self.assets})
        if url.startswith(PREFIX):
            name = url.removeprefix(PREFIX)
            return httpx.Response(302, headers={"Location": f"https://{self.redirect_host}/blob/{name}"})
        if request.url.host == "objects.githubusercontent.com":
            name = request.url.path.rsplit("/", 1)[-1]
            return httpx.Response(200, content=self.sums if name == "SHA256SUMS" else self.wheel)
        return httpx.Response(404)


def args(check=False, yes=False):
    return SimpleNamespace(check=check, yes=yes)


def test_versions_compare_numerically():
    assert update.newer("0.10.0", "0.9.9") and update.newer("v1.0.0", "0.3.0")
    assert not update.newer("0.3.0", "0.3.0") and not update.newer("0.2.9", "0.3.0")
    assert not update.newer("0.4.0-rc1", "0.3.0") and not update.newer(None, "0.3.0")


def test_check_only_reports(capsys):
    github = GitHub()
    code = update.run(args(check=True), transport=httpx.MockTransport(github))
    assert code == 0
    assert json.loads(capsys.readouterr().out) == {
        "installed": __version__, "latest": "9.8.7", "update_available": True}
    assert [str(r.url) for r in github.requests] == [update.LATEST_URL]  # nothing downloaded
    assert update.read_cache()["latest"] == "9.8.7"


def test_update_verifies_hash_then_runs_uv(capsys):
    calls = []

    def runner(argv):
        calls.append(argv)
        assert open(argv[-1], "rb").read() == WHEEL  # the verified wheel exists at install time
        return SimpleNamespace(returncode=0)

    code = update.run(args(yes=True), transport=httpx.MockTransport(GitHub()),
                      runner=runner, which=lambda name: "/opt/bin/uv")
    assert code == 0
    assert calls and calls[0][:4] == ["/opt/bin/uv", "tool", "install", "--force"]
    assert calls[0][-1].endswith(WHEEL_NAME)
    assert "SHA-256 verified" in capsys.readouterr().out


def test_checksum_mismatch_installs_nothing(capsys):
    calls = []
    github = GitHub(wheel=b"tampered")
    code = update.run(args(yes=True), transport=httpx.MockTransport(github),
                      runner=lambda argv: calls.append(argv), which=lambda name: "/opt/bin/uv")
    assert code == 1 and calls == []
    assert "Checksum mismatch" in capsys.readouterr().err


@pytest.mark.parametrize("assets", [
    [{"name": WHEEL_NAME, "browser_download_url": PREFIX + WHEEL_NAME}],  # no SHA256SUMS
    [{"name": WHEEL_NAME, "browser_download_url": "https://evil.example/" + WHEEL_NAME},
     {"name": "SHA256SUMS", "browser_download_url": PREFIX + "SHA256SUMS"}],
    [{"name": "../../x.whl", "browser_download_url": PREFIX + "../../x.whl"},
     {"name": "SHA256SUMS", "browser_download_url": PREFIX + "SHA256SUMS"}],
])
def test_release_without_verifiable_assets_is_refused(assets, capsys):
    calls = []
    code = update.run(args(yes=True), transport=httpx.MockTransport(GitHub(assets=assets)),
                      runner=lambda argv: calls.append(argv), which=lambda name: "/opt/bin/uv")
    assert code == 1 and calls == []


def test_redirect_to_unexpected_host_is_refused(capsys):
    code = update.run(args(yes=True), transport=httpx.MockTransport(GitHub(redirect_host="evil.example")),
                      runner=lambda argv: pytest.fail("installed"), which=lambda name: "/opt/bin/uv")
    assert code == 1 and "unexpected host" in capsys.readouterr().err


def test_missing_uv_prints_the_command(capsys):
    code = update.run(args(yes=True), transport=httpx.MockTransport(GitHub()), which=lambda name: None)
    out = capsys.readouterr().out
    assert code == 1 and f"uv tool install --force ./{WHEEL_NAME}" in out


def test_prompt_declined_changes_nothing(capsys):
    code = update.run(args(), transport=httpx.MockTransport(GitHub()), which=lambda name: "/opt/bin/uv",
                      runner=lambda argv: pytest.fail("installed"), ask=lambda prompt: "n")
    assert code == 0 and "Nothing was changed" in capsys.readouterr().out


def test_up_to_date(capsys):
    code = update.run(args(), transport=httpx.MockTransport(GitHub(tag="v" + __version__)))
    assert code == 0 and "up to date" in capsys.readouterr().out


class TTY(io.StringIO):
    def isatty(self):
        return True


def test_passive_notice_once_a_day(monkeypatch):
    monkeypatch.delenv("NETCONVERTER_NO_UPDATE_CHECK")
    github = GitHub()
    stream = TTY()
    update.notify(stream, transport=httpx.MockTransport(github), background=False)
    assert stream.getvalue() == ""  # first run only refreshes the cache
    assert len(github.requests) == 1
    update.notify(stream, transport=httpx.MockTransport(github), background=False)
    assert "9.8.7 is available" in stream.getvalue() and "netconverter update" in stream.getvalue()
    update.notify(stream, transport=httpx.MockTransport(github), background=False)
    assert stream.getvalue().count("is available") == 1  # once a day
    assert len(github.requests) == 1  # one check a day


def test_passive_notice_is_silent_when_disabled_or_not_a_terminal(monkeypatch):
    def boom(request):
        raise AssertionError("network")

    stream = TTY()
    update.notify(stream, transport=httpx.MockTransport(boom), background=False)  # disabled by env
    monkeypatch.delenv("NETCONVERTER_NO_UPDATE_CHECK")
    update.notify(io.StringIO(), transport=httpx.MockTransport(boom), background=False)  # not a TTY
    assert stream.getvalue() == ""


def test_passive_check_swallows_errors(monkeypatch):
    monkeypatch.delenv("NETCONVERTER_NO_UPDATE_CHECK")

    def offline(request):
        raise httpx.ConnectError("offline")

    stream = TTY()
    update.notify(stream, transport=httpx.MockTransport(offline), background=False)
    assert stream.getvalue() == ""
    assert time.time() - update.read_cache()["checked_at"] < 60  # no retry storm while offline


def test_cli_update_never_needs_a_workspace(monkeypatch, tmp_path):
    from netconverter_cli import cli

    seen = {}
    monkeypatch.setattr(update, "run", lambda a: seen.setdefault("args", a) and 0)
    with pytest.raises(SystemExit):
        cli.main(["--workspace", str(tmp_path / "gone"), "update", "--check"])
    assert seen["args"].check is True


def test_mcp_command_never_runs_the_notice(monkeypatch):
    from netconverter_cli import cli

    monkeypatch.setattr(update, "notify", lambda *a, **k: pytest.fail("notice in mcp"))
    monkeypatch.setattr(cli, "run_mcp", lambda a: None)
    cli.main(["mcp", "--no-remote"])


def test_status_for_account_tool(monkeypatch):
    assert update.status() == {"latest": None, "update_available": None}  # disabled
    monkeypatch.delenv("NETCONVERTER_NO_UPDATE_CHECK")
    assert update.status(transport=httpx.MockTransport(GitHub())) == {
        "latest": "9.8.7", "update_available": True}


def receipt(folder, requirement):
    folder.mkdir()
    (folder / "uv-receipt.toml").write_text(f"[tool]\nrequirements = [{requirement}]\n")
    return folder


def test_pypi_install_is_detected_from_the_uv_receipt(tmp_path):
    index = receipt(tmp_path / "index", '{ name = "netconverter-cli" }')
    wheel = receipt(tmp_path / "wheel", '{ name = "netconverter-cli", path = "/tmp/x.whl" }')
    assert update.from_pypi(index, direct_url=lambda: False)
    assert not update.from_pypi(index, direct_url=lambda: True)  # dist metadata says file/URL install
    assert not update.from_pypi(wheel, direct_url=lambda: False)
    assert not update.from_pypi(tmp_path / "none", direct_url=lambda: False)  # pip/venv, no receipt


def test_pypi_install_runs_uv_tool_upgrade(capsys):
    calls = []
    github = GitHub()
    code = update.run(args(yes=True), transport=httpx.MockTransport(github), which=lambda name: "/opt/bin/uv",
                      runner=lambda argv: calls.append(argv) or SimpleNamespace(returncode=0),
                      pypi=lambda: True)
    assert code == 0 and calls == [["/opt/bin/uv", "tool", "upgrade", "netconverter-cli"]]
    assert [str(r.url) for r in github.requests] == [update.LATEST_URL]  # no wheel download
    assert "PyPI" in capsys.readouterr().out


def test_pypi_upgrade_failure_is_reported(capsys):
    code = update.run(args(yes=True), transport=httpx.MockTransport(GitHub()), which=lambda name: "/opt/bin/uv",
                      runner=lambda argv: SimpleNamespace(returncode=2), pypi=lambda: True)
    assert code == 1 and "uv tool upgrade failed" in capsys.readouterr().err


def test_version_flag(capsys):
    from netconverter_cli import cli

    with pytest.raises(SystemExit):
        cli.main(["--version"])
    assert capsys.readouterr().out.strip() == f"netconverter-cli {__version__}"
