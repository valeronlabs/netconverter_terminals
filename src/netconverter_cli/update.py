"""`netconverter update` and the once-a-day "new version available" notice.

Only the public GitHub Releases API of this repository is contacted, without
credentials: no NetConverter key or sign-in is ever sent there. A copy that uv
installed from PyPI is upgraded with ``uv tool upgrade``; any other copy gets the
release wheel, installed only after its SHA-256 matches ``SHA256SUMS``. The
passive check runs in a background thread with a short timeout, writes a small
cache file, swallows every error and never prints to stdout.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import tomllib
from importlib import metadata
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from . import __version__

REPO = "valeronlabs/netconverter_terminals"
DIST = "netconverter-cli"
LATEST_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
DOWNLOAD_PREFIX = f"https://github.com/{REPO}/releases/download/"
# GitHub answers an asset download with a redirect to its object storage.
DOWNLOAD_HOSTS = frozenset({"github.com", "objects.githubusercontent.com",
                            "release-assets.githubusercontent.com"})
CHECK_INTERVAL_S = 24 * 3600
NOTICE_TIMEOUT_S = 3.0
MAX_WHEEL_BYTES = 50 * 1024 * 1024
MAX_SUMS_BYTES = 64 * 1024
MAX_API_BYTES = 1024 * 1024
_VERSION = re.compile(r"v?(\d{1,4})\.(\d{1,4})\.(\d{1,4})\Z")
_WHEEL = re.compile(r"netconverter_cli-(\d{1,4}\.\d{1,4}\.\d{1,4})-py3-none-any\.whl\Z")
_HEX = re.compile(r"[0-9a-f]{64}\Z")


class UpdateError(RuntimeError):
    pass


def disabled() -> bool:
    return os.getenv("NETCONVERTER_NO_UPDATE_CHECK") == "1"


def parse_version(text) -> tuple | None:
    """(major, minor, patch) for a plain release version; None for anything else (pre-releases)."""
    match = _VERSION.fullmatch(str(text or "").strip())
    return tuple(int(part) for part in match.groups()) if match else None


def newer(latest, installed=__version__) -> bool:
    a, b = parse_version(latest), parse_version(installed)
    return bool(a and b and a > b)


def cache_dir() -> Path:
    """The per-user cache folder (never the workspace)."""
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / "netconverter"
    if os.name == "nt":
        base = os.getenv("LOCALAPPDATA")
        return (Path(base) if base else Path.home() / "AppData" / "Local") / "netconverter" / "Cache"
    base = os.getenv("XDG_CACHE_HOME")
    return (Path(base) if base else Path.home() / ".cache") / "netconverter"


def _cache_file() -> Path:
    return cache_dir() / "update-check.json"


def read_cache() -> dict:
    try:
        data = json.loads(_cache_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def write_cache(**fields) -> None:
    path = _cache_file()
    data = {**read_cache(), **fields}
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".update-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(data, stream)
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


# -- GitHub ---------------------------------------------------------------


def _http(transport=None, timeout=10.0) -> httpx.Client:
    return httpx.Client(timeout=timeout, transport=transport, follow_redirects=False, trust_env=False,
                        headers={"Accept": "application/vnd.github+json",
                                 "User-Agent": f"netconverter-cli/{__version__}"})


def latest_release(*, transport=None, timeout=10.0) -> dict:
    """{version, tag, wheel_name, wheel_url, sums_url}; sums_url/wheel_* may be None."""
    with _http(transport, timeout) as http:
        try:
            response = http.get(LATEST_URL)
        except httpx.HTTPError:
            raise UpdateError("Could not reach GitHub to check for a new release") from None
    if response.status_code == 404:
        raise UpdateError("No published release was found")
    if response.is_error or len(response.content) > MAX_API_BYTES:
        raise UpdateError(f"GitHub answered HTTP {response.status_code}")
    try:
        body = response.json()
    except ValueError:
        raise UpdateError("GitHub returned an invalid response") from None
    tag = body.get("tag_name") if isinstance(body, dict) else None
    version = parse_version(tag)
    if version is None:
        raise UpdateError("The latest release has no plain version tag")
    out = {"version": ".".join(map(str, version)), "tag": str(tag), "wheel_name": None,
           "wheel_url": None, "sums_url": None}
    for asset in body.get("assets") or []:
        if not isinstance(asset, dict):
            continue
        name, url = asset.get("name"), asset.get("browser_download_url")
        if not isinstance(name, str) or not isinstance(url, str) or url != f"{DOWNLOAD_PREFIX}{tag}/{name}":
            continue
        wheel = _WHEEL.fullmatch(name)
        if wheel and wheel.group(1) == out["version"]:
            out["wheel_name"], out["wheel_url"] = name, url
        elif name == "SHA256SUMS":
            out["sums_url"] = url
    return out


def _download(http: httpx.Client, url: str, limit: int) -> bytes:
    for _ in range(5):  # bounded redirects, each to an allowlisted HTTPS host
        parts = urlsplit(url)
        if parts.scheme != "https" or (parts.hostname or "") not in DOWNLOAD_HOSTS:
            raise UpdateError("Release download redirected to an unexpected host")
        try:
            with http.stream("GET", url, headers={"Accept": "application/octet-stream"}) as response:
                if response.is_redirect:
                    url = str(response.url.join(response.headers.get("location", "")))
                    continue
                if response.is_error:
                    raise UpdateError(f"Release download failed (HTTP {response.status_code})")
                chunks, size = [], 0
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > limit:
                        raise UpdateError("Release asset is larger than expected")
                    chunks.append(chunk)
                return b"".join(chunks)
        except httpx.HTTPError:
            raise UpdateError("Release download failed") from None
    raise UpdateError("Too many redirects downloading the release")


def expected_hash(sums: bytes, filename: str) -> str:
    for line in sums.decode("utf-8", "replace").splitlines():
        parts = line.strip().split()
        if len(parts) == 2 and parts[1].lstrip("*") == filename and _HEX.fullmatch(parts[0].lower()):
            return parts[0].lower()
    raise UpdateError(f"SHA256SUMS has no entry for {filename}")


def fetch_verified_wheel(release: dict, dest: Path, *, transport=None) -> Path:
    if not release.get("wheel_url") or not release.get("sums_url"):
        raise UpdateError("The latest release has no wheel and SHA256SUMS to verify")
    with _http(transport, 60.0) as http:
        sums = _download(http, release["sums_url"], MAX_SUMS_BYTES)
        wheel = _download(http, release["wheel_url"], MAX_WHEEL_BYTES)
    want = expected_hash(sums, release["wheel_name"])
    got = hashlib.sha256(wheel).hexdigest()
    if got != want:
        raise UpdateError(f"Checksum mismatch for {release['wheel_name']}; nothing was installed")
    path = Path(dest) / release["wheel_name"]
    path.write_bytes(wheel)
    return path


# -- how this copy was installed ------------------------------------------

# Receipt keys that mean uv installed from a file, URL or checkout, not the index.
_DIRECT_KEYS = ("path", "url", "git", "directory", "editable")


def _has_direct_url() -> bool:
    """PEP 610: a wheel, URL or checkout install records direct_url.json; an index install does not."""
    try:
        return metadata.distribution(DIST).read_text("direct_url.json") is not None
    except metadata.PackageNotFoundError:
        return True


def from_pypi(prefix=None, direct_url=_has_direct_url) -> bool:
    """True when this copy is a `uv tool install netconverter-cli` from the package index."""
    try:
        receipt = tomllib.loads((Path(prefix or sys.prefix) / "uv-receipt.toml").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    for req in (receipt.get("tool") or {}).get("requirements") or []:
        if isinstance(req, dict) and req.get("name") == DIST:
            return not any(key in req for key in _DIRECT_KEYS) and not direct_url()
    return False


# -- `netconverter update` ------------------------------------------------


def run(args, *, transport=None, runner=subprocess.run, which=shutil.which, ask=input,
        pypi=from_pypi) -> int:
    try:
        release = latest_release(transport=transport)
    except UpdateError as exc:
        print(f"netconverter update: {exc}", file=sys.stderr)
        return 1
    available = newer(release["version"])
    try:
        write_cache(checked_at=time.time(), latest=release["version"])
    except OSError:
        pass
    if args.check:
        if getattr(args, "json", False):
            print(json.dumps({"installed": __version__, "latest": release["version"],
                              "update_available": available}))
        elif available:
            print(f"Update available: {__version__} → {release['version']}. Run `netconverter update`.")
        else:
            print(f"NetConverter CLI {__version__} is up to date.")
        return 0
    if not available:
        print(f"NetConverter CLI {__version__} is up to date (latest release {release['version']}).")
        return 0
    uv = which("uv")
    if uv and pypi():
        return _upgrade_from_pypi(args, release, uv, runner, ask)
    if not uv:
        print(f"NetConverter CLI {release['version']} is available (installed {__version__}), "
              "but uv is not on PATH. Download the wheel and SHA256SUMS from\n"
              f"  https://github.com/{REPO}/releases/tag/{release['tag']}\n"
              "verify it with `shasum -a 256 -c SHA256SUMS`, then run:\n"
              f"  uv tool install --force ./{release['wheel_name'] or 'netconverter_cli-<version>-py3-none-any.whl'}")
        return 1
    print(f"Update NetConverter CLI {__version__} → {release['version']} "
          f"(verified wheel from github.com/{REPO}).")
    if not args.yes and ask("Install it now? [y/N] ").strip().lower() not in {"y", "yes"}:
        print("Nothing was changed.")
        return 0
    with tempfile.TemporaryDirectory(prefix="netconverter-update-") as tmp:
        try:
            wheel = fetch_verified_wheel(release, Path(tmp), transport=transport)
        except UpdateError as exc:
            print(f"netconverter update: {exc}", file=sys.stderr)
            return 1
        print(f"SHA-256 verified: {wheel.name}")
        done = runner([uv, "tool", "install", "--force", str(wheel)])
    if done.returncode != 0:
        print("uv tool install failed; your current version is unchanged.", file=sys.stderr)
        return 1
    print(f"Installed NetConverter CLI {release['version']}.")
    return 0


def _upgrade_from_pypi(args, release, uv, runner, ask) -> int:
    print(f"Update NetConverter CLI {__version__} → {release['version']} (PyPI, `uv tool upgrade {DIST}`).")
    if not args.yes and ask("Upgrade it now? [y/N] ").strip().lower() not in {"y", "yes"}:
        print("Nothing was changed.")
        return 0
    if runner([uv, "tool", "upgrade", DIST]).returncode != 0:
        print("uv tool upgrade failed; your current version is unchanged.", file=sys.stderr)
        return 1
    print("Upgraded NetConverter CLI from PyPI. Run `netconverter --version` to confirm.")
    return 0


# -- passive check --------------------------------------------------------


def cached_status() -> dict:
    """{latest, update_available} from the cache only; never touches the network."""
    latest = read_cache().get("latest")
    return {"latest": latest if parse_version(latest) else None,
            "update_available": newer(latest) if parse_version(latest) else None}


def refresh(*, transport=None, timeout=NOTICE_TIMEOUT_S) -> None:
    """One bounded check that updates the cache. Errors are swallowed."""
    try:
        release = latest_release(transport=transport, timeout=timeout)
        write_cache(checked_at=time.time(), latest=release["version"])
    except Exception:
        try:
            write_cache(checked_at=time.time())  # do not retry on every command while offline
        except Exception:
            pass


def _stale(now=None) -> bool:
    checked = read_cache().get("checked_at")
    return not isinstance(checked, (int, float)) or (now or time.time()) - checked >= CHECK_INTERVAL_S


def status(*, transport=None, timeout=NOTICE_TIMEOUT_S) -> dict:
    """For the MCP `account` tool: the cache, refreshed (bounded) when older than a day."""
    if disabled():
        return {"latest": None, "update_available": None}
    try:
        if _stale():
            refresh(transport=transport, timeout=timeout)
        return cached_status()
    except Exception:
        return {"latest": None, "update_available": None}


def notify(stream=None, *, transport=None, background=True) -> None:
    """At most once a day, a one-line notice on stderr. Never blocks or raises."""
    try:
        stream = stream or sys.stderr
        if disabled() or not stream.isatty():
            return
        now = time.time()
        state = cached_status()
        notified = read_cache().get("notified_at")
        recently = isinstance(notified, (int, float)) and now - notified < CHECK_INTERVAL_S
        if state["update_available"] and not recently:
            stream.write(f"NetConverter CLI {state['latest']} is available (installed {__version__}). "
                         "Run `netconverter update`. Set NETCONVERTER_NO_UPDATE_CHECK=1 to hide this.\n")
            write_cache(notified_at=now)
        if _stale(now):
            if background:
                threading.Thread(target=refresh, kwargs={"transport": transport}, daemon=True).start()
            else:
                refresh(transport=transport)
    except Exception:
        pass
