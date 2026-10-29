"""Independent terminal executable; importing it never imports appliance code."""

import argparse
import difflib
import getpass
import json
import os
import re
import sys
from pathlib import Path
from .api import Client, DEFAULT_BASE, APIError
from .backend import detect_profile, open_client
from .credentials import (KeyringLocked, get_secret, keyring_available, keyring_problem, load_secret,
                          save_secret)
from .controller import Controller
from .providers import Provider, ProviderError
from .commands import execute
from .job_options import OptionsError
from .setup import configure, load_settings, account
from .remote_mcp import DEFAULT_MCP_URL
from .clerk import ClerkError
from .errors import (CANCELLED, EXIT_AUTH, EXIT_CANCELLED, EXIT_FAILURE, EXIT_INPUT, EXIT_USAGE,
                     KEYRING_LOCKED, OPTIONS_EXAMPLE, SIGNED_OUT, CommandError, api_error_message, api_exit_code)
from .workspace import Workspace, WorkspaceError


# A Clerk token is the user's NetConverter identity. It is only ever sent to
# these hosts (over https). A workspace folder is untrusted input — a shared or
# cloned folder can carry a .netconverter/connection.json — so neither its
# "server" nor its "auth" may route the token anywhere else. Staging or a
# self-hosted endpoint is trusted explicitly by the USER's own environment:
# NETCONVERTER_TRUSTED_HOSTS=host1,host2.
TRUSTED_CLERK_HOSTS = frozenset({"api.netconverter.ai"})


def trusted_clerk_hosts() -> frozenset:
    extra = {h.strip().lower() for h in os.getenv("NETCONVERTER_TRUSTED_HOSTS", "").split(",") if h.strip()}
    return TRUSTED_CLERK_HOSTS | extra


def clerk_allowed(url: str) -> bool:
    from urllib.parse import urlsplit

    try:
        parts = urlsplit(url or "")
    except ValueError:
        return False
    return parts.scheme == "https" and (parts.hostname or "").lower() in trusted_clerk_hosts()


def clerk_preferred(settings) -> bool:
    """Clerk as the default credential stays opt-in until the server accepts it.

    Chosen by the user's environment only — never by the workspace's
    connection.json (``settings``), which a shared folder could carry.
    """
    return os.getenv("NETCONVERTER_AUTH", "key") == "clerk"


def workspace_server_trusted(url: str) -> bool:
    """A server named by a workspace file: a trusted NetConverter host, or loopback for development."""
    from urllib.parse import urlsplit

    if clerk_allowed(url):
        return True
    try:
        parts = urlsplit(url or "")
    except ValueError:
        return False
    return parts.scheme in {"http", "https"} and (parts.hostname or "") in {"127.0.0.1", "localhost", "::1"}


def mcp_url_for(server: str) -> str:
    base = server.rstrip("/")
    if base.endswith("/external/v1"):
        return base[: -len("/external/v1")] + "/mcp/v1/"
    return DEFAULT_MCP_URL


def _clerk_session():
    from .clerk import ClerkSession

    session = ClerkSession()
    return session if session.signed_in else None


def rest_credential(server, settings, *, interactive=True):
    """The credential plain commands use: a stored key, else the sign-in.

    NETCONVERTER_AUTH=key|clerk (the user's environment, never the workspace's
    connection.json) forces one; unset, a stored key wins and the sign-in is
    used only for a trusted NetConverter host.
    """
    mode = os.getenv("NETCONVERTER_AUTH", "auto")
    if mode == "clerk":
        if not clerk_allowed(server):
            raise CommandError(f"Refusing to send your NetConverter sign-in to {server}: not a trusted "
                               "NetConverter host (set NETCONVERTER_TRUSTED_HOSTS to trust it explicitly)",
                               EXIT_USAGE)
        session = _clerk_session()
        if session is None:
            raise CommandError(SIGNED_OUT, EXIT_AUTH)
        return session
    if mode == "key":
        key = get_secret(account(server), prompt=interactive, label=_host(server))
        if not key:
            raise CommandError(SIGNED_OUT, EXIT_AUTH)
        return key
    key = get_secret(account(server), prompt=False)
    if key:
        return key
    if clerk_allowed(server):
        session = _clerk_session()
        if session is not None:
            return session
    if not keyring_available() and interactive:
        # no credential store: a memory-only key prompt
        key = get_secret(account(server), label=_host(server))
        if key:
            return key
    raise CommandError(SIGNED_OUT, EXIT_AUTH)


def _host(server: str) -> str:
    from urllib.parse import urlsplit

    try:
        return urlsplit(server).hostname or server
    except ValueError:
        return server


def clerk_login(args, settings):
    from .clerk import ClerkError, REDIRECT_URI, login, ClerkSession, profile_summary

    try:
        login(device=args.device, notify=lambda text: print(text, file=sys.stderr))
        try:
            profile = profile_summary(ClerkSession().userinfo())
        except ClerkError:
            profile = {}
    except ClerkError as exc:
        print(str(exc), file=sys.stderr)
        if not args.device:
            print(f"If the browser reported a redirect error, {REDIRECT_URI} must be a "
                  "registered redirect URI for this OAuth application.", file=sys.stderr)
        raise SystemExit(1) from None
    print(json.dumps({"signed_in": True, "method": "clerk", **profile,
                      "credential_storage": "OS credential store"}, ensure_ascii=False))


def logout(args):
    from .clerk import ClerkSession
    from .credentials import delete_secret

    result = {"clerk_signed_out": ClerkSession().revoke_and_clear()}
    if args.all:
        result["api_key_removed"] = delete_secret(account(args.server))
    print(json.dumps(result))


def whoami(args):
    from .clerk import ClerkError, profile_summary

    out = {"server": args.server, "api_key_stored": bool(load_secret(account(args.server))),
           "api_key_in_environment": bool(os.environ.get("NETCONVERTER_API_KEY"))}
    session = _clerk_session()
    if session is None:
        out["clerk"] = None
    else:
        try:
            out["clerk"] = {"signed_in": True, **profile_summary(session.userinfo())}
        except ClerkError as exc:
            out["clerk"] = {"signed_in": False, "message": str(exc)}
    print(json.dumps(out, indent=2, ensure_ascii=False))


MCP_AUTH_MODES = ("auto", "clerk", "key")
# Exposure levels (#13) plus the 0.4.x name strict (= masked).
MCP_VIEWS = ("none", "masked", "selected", "full", "strict")


def mcp_view_default() -> str | None:
    """`mcp --level` default: NETCONVERTER_MCP_VIEW when it names a level, else None (the folder's level).

    A flag or the variable can only lower the folder's level for one process (#13);
    the folder's level itself changes only with `netconverter privacy level`.
    """
    value = os.getenv("NETCONVERTER_MCP_VIEW", "")
    return value if value in MCP_VIEWS else None


def mcp_auth_default() -> str:
    """`mcp --auth` default: NETCONVERTER_MCP_AUTH, else NETCONVERTER_AUTH (#16), else auto."""
    for name in ("NETCONVERTER_MCP_AUTH", "NETCONVERTER_AUTH"):
        value = os.getenv(name, "")
        if value in MCP_AUTH_MODES:
            return value
    return "auto"


def choose_mcp_credential(auth: str, server: str, mcp_url: str):
    """A locked keyring starts the bridge without a credential and says why (#10)."""
    try:
        return _choose_mcp_credential(auth, server, mcp_url)
    except KeyringLocked:
        return None, None, "none", [f"credential: none; {KEYRING_LOCKED}"]


def _choose_mcp_credential(auth: str, server: str, mcp_url: str):
    """One principal for the whole bridge process (#16).

    Returns (rest_credential, remote_credential, source, notes). REST and the
    remote tools always get the same credential: ``auto`` prefers the signed-in
    session and names the API key it leaves unused; a key is used only when
    chosen (``--auth key`` / NETCONVERTER_AUTH=key) or when there is no
    sign-in. A sign-in still goes only to trusted NetConverter hosts.
    """
    key = get_secret(account(server), prompt=False) if auth in ("auto", "key") else ""
    key_source = "api_key_environment" if key and os.environ.get("NETCONVERTER_API_KEY") == key else "api_key_stored"
    key_label = "NETCONVERTER_API_KEY" if key_source == "api_key_environment" else "the API key in the OS credential store"
    session = _clerk_session() if auth in ("auto", "clerk") else None
    rest_session = session if session is not None and clerk_allowed(server) else None
    remote_session = session if session is not None and clerk_allowed(mcp_url) else None
    notes = []
    if session is not None and (rest_session is None or remote_session is None):
        notes.append("your sign-in is only sent to trusted NetConverter hosts; "
                     "an untrusted server or MCP URL will not receive it")
    if auth == "key":
        return (key or None, key or None, key_source if key else "none",
                notes + [f"credential: {key_label} (--auth key)" if key else "credential: none (--auth key, no API key)"])
    if auth == "clerk" or (session is not None and rest_session is not None and remote_session is not None):
        if auth == "auto" and key:
            notes.append(f"credential: Clerk sign-in; ignoring {key_label} (NETCONVERTER_AUTH=key or "
                         "--auth key chooses the key instead)")
        elif session is not None:
            notes.append("credential: Clerk sign-in" + (" (--auth clerk)" if auth == "clerk" else ""))
        else:
            notes.append("credential: none (not signed in; run `netconverter login --clerk`)")
        return rest_session, remote_session, "clerk_session" if session is not None else "none", notes
    if key:  # auto: no usable sign-in, so the key serves both surfaces
        notes.append(f"credential: {key_label}" + (" (sign-in present but not usable for this host)"
                                                   if session is not None else ""))
        return key, key, key_source, notes
    if session is not None:  # auto: a sign-in usable on one surface only; never a second principal
        notes.append("credential: Clerk sign-in")
        return rest_session, remote_session, "clerk_session", notes
    problem = keyring_problem()
    if problem:  # an AI client started us without the desktop keyring (#17): say so, not "sign in"
        notes.append(f"credential: none; {problem}. Start this MCP server with "
                     "DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/<uid>/bus in its environment, "
                     "or set NETCONVERTER_API_KEY there.")
    else:
        notes.append("credential: none (run `netconverter login --clerk`, or store an API key with `netconverter login`)")
    return None, None, "none", notes


def run_mcp(args):
    from .mcp_server import Bridge, run_stdio
    from .remote_mcp import RemoteMCP
    from . import __version__

    mcp_url = args.mcp_url or mcp_url_for(args.server)
    rest, remote_credential, source, notes = choose_mcp_credential(args.auth, args.server, mcp_url)
    for note in notes:
        print(f"netconverter mcp: {note}", file=sys.stderr)
    guided = bool(getattr(args, "guided", False))
    cap, effective = mcp_exposure(args, guided)
    strict = effective.strict
    if not strict:
        print("netconverter mcp: full view (exposure level full): the assistant can call every allowlisted "
              "remote tool, and results show this tenant's own addresses and names", file=sys.stderr)
    remote = None
    if remote_credential is not None and not args.no_remote and not guided:
        # The level goes to the server on every request; it applies min(grant, level) (#13, #15).
        remote = RemoteMCP(mcp_url, remote_credential, client_version=__version__, view_mode=effective.level)
    try:
        options = {"guided": True} if guided else {}
        if rest is None:  # a sign-in made after start is used on the next call, no restart (#21)
            options["credential_loader"] = lambda: choose_mcp_credential(args.auth, args.server, mcp_url)
        run_stdio(Bridge(args.workspace, args.server, rest, remote, strict=strict,
                         credential_source=source, level=cap.level, sections=cap.sections,
                         workspace_level=True, **options))
    finally:
        if remote:
            remote.close()


def mcp_exposure(args, guided: bool):
    """(cap, effective) exposure for `netconverter mcp` (#13; docs/PRIVACY.md § Exposure levels).

    The folder's level (`netconverter privacy level`, default masked) is the most
    the bridge serves. --level/--strict/--full, else NETCONVERTER_MCP_VIEW, can only
    lower it for this process. Guided mode serves at most masked and needs more than none.
    """
    from . import exposure

    root = Path(args.workspace or ".")
    folder = exposure.load(root)
    requested = getattr(args, "view", None)
    if requested:
        level = exposure.normalize(requested)
        # A requested `selected` keeps the folder's own sections.
        cap = exposure.Exposure(level, tuple(exposure.SECTIONS) if level == "selected" else ())
    else:
        cap = exposure.Exposure("full")
    effective = exposure.lower(folder, cap)
    if guided:
        if effective.level == "none":
            raise CommandError("netconverter mcp --guided needs exposure level masked or higher; this folder "
                               "is at none (`netconverter privacy level masked`).", EXIT_USAGE)
        effective = exposure.lower(effective, exposure.Exposure("masked"))
    if requested and exposure.is_raise(folder, cap) and cap.level != "selected":
        print(f"netconverter mcp: --level {cap.level} asks for more than this folder allows "
              f"({folder.describe()}); raise it in a terminal with `netconverter privacy level {cap.level}`",
              file=sys.stderr)
    print(f"netconverter mcp: exposure level {effective.describe()} (this folder: {folder.describe()})",
          file=sys.stderr)
    return cap, effective


def check_source_vendor(vendor: str, catalog) -> None:
    """Refuse a source vendor code the server does not list, naming the valid ones (#22).

    There is no ``auto``: detection exists only in the guided flow. A catalogue
    without a vendor list (an older server) cannot judge, so the server decides.
    """
    sources = sorted(code for code, v in catalog.vendors.items() if "source" in (v.get("roles") or ["source"]))
    if not vendor:  # #8: name the codes instead of argparse's bare "required"
        raise CommandError(VENDOR_REQUIRED + (f" Valid --vendor codes: {', '.join(sources)}." if sources else
                                              " `netconverter capabilities` lists the codes."), EXIT_USAGE)
    if not catalog.loaded or vendor in catalog.vendors:
        return
    raise CommandError(f"netconverter: unknown source vendor {vendor!r} (there is no 'auto'). "
                       f"Valid --vendor codes: {', '.join(sources) or 'none listed'}; "
                       "`netconverter capabilities` shows names and conversion paths.", EXIT_USAGE)


SUBMIT_COMMANDS = ("validate", "analyze", "optimize", "convert")
VENDOR_REQUIRED = "--vendor is required: the source vendor code of the file."


def check_submission(args) -> dict:
    """Local checks for a one-shot submit, before any sign-in or network call (#9).

    Returns the parsed --options. The size limit is the full API's ceiling here;
    the profile's own limit is applied again when the file is selected.
    """
    from .backend import EXTERNAL_MAX_BYTES

    try:
        options = json.loads(args.options)
    except ValueError as exc:
        raise CommandError(f"--options is not valid JSON ({exc}). Example: {OPTIONS_EXAMPLE}", EXIT_INPUT) from None
    if not isinstance(options, dict):
        raise CommandError(f"--options must be a JSON object. Example: {OPTIONS_EXAMPLE}", EXIT_INPUT)
    workspace = Workspace(args.workspace)
    try:
        path = workspace.locate(args.file)
        if not path.exists():
            raise WorkspaceError(f"File not found: {args.file} (looked in {workspace.root})")
        if path.is_file() and path.stat().st_size == 0:
            raise WorkspaceError(f"{args.file} is empty; choose the saved configuration file")
        workspace.snapshot(args.file, EXTERNAL_MAX_BYTES)
    except WorkspaceError as exc:
        raise CommandError(str(exc), EXIT_INPUT) from None
    return options


def remote_for(server, credential):
    """The NetConverter MCP endpoint for questions, only over a trusted host for a sign-in."""
    from .remote_mcp import RemoteMCP
    from . import __version__

    url = mcp_url_for(server)
    if getattr(credential, "kind", "key") != "key" and not clerk_allowed(url):
        return None
    return RemoteMCP(url, credential, client_version=__version__)


def run_connect(args, ask=input):
    from .connect import CLIENTS, configured_clients, installed_local_clients, plan

    root = Path(args.workspace).resolve()
    if getattr(args, "all", False):
        targets = [k for k in installed_local_clients() if CLIENTS[k].title not in configured_clients(root)]
        if not targets:
            print("Every AI assistant found on this computer is already connected.")
            return
        print("Connecting: " + ", ".join(CLIENTS[k].title for k in targets) + "\n")
        failed = 0
        for key in targets:
            try:
                _connect_one(argparse.Namespace(**{**vars(args), "client": key, "all": False, "batch": True}),
                             root, ask)
            except SystemExit as exc:
                failed += 1 if exc.code else 0
            print()
        print("Restart each assistant to load the netconverter tools.")
        if failed:
            raise SystemExit(1)
        return
    if not args.client:
        done = configured_clients(root)
        found = set(installed_local_clients())
        for key, spec in CLIENTS.items():
            if spec.kind == "remote":
                mark, note = "↗", "remote connector (setup steps)"
            elif spec.title in done:
                mark, note = "●", "connected"
            else:
                mark, note = "○", "found on this computer" if key in found else ""
            print(f"  {mark} {key:<15} {spec.title:<28} {note}".rstrip())
        print("\nnetconverter connect <client>   shows the change, then asks before applying it")
        print("netconverter connect --all      connects every assistant found on this computer")
        return
    _connect_one(args, root, ask)


def _connect_one(args, root, ask):
    from .connect import CLIENTS, plan, plan_remove

    change = (plan_remove if getattr(args, "remove", False) else plan)(args.client, root)
    print(f"{change.title}: {change.summary}\n\n{change.preview}\n")
    if args.print_only:
        for extra in change.followups:
            print(f"{extra.title} (offered after applying): {extra.summary}\n\n{extra.preview}\n")
        return
    if not change.can_apply:
        print(change.manual)
        if CLIENTS.get(args.client) and CLIENTS[args.client].kind == "remote":
            return  # setup steps, not a failure
        raise SystemExit(1)
    if not args.yes and ask(f"Apply to {change.where}? [y/N] ").strip().lower() not in {"y", "yes"}:
        print("Nothing was changed.")
        return
    try:
        print(change.apply())
    except Exception as exc:
        print(f"Could not apply: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
    for extra in change.followups:
        print(f"\n{extra.title}: {extra.summary}\n\n{extra.preview}\n")
        if not extra.can_apply:
            print(extra.manual)
            continue
        if getattr(args, "batch", False):  # connect --all: optional extras need their own run
            print(f"Skipped in --all; run `netconverter connect {args.client}` to review it.")
            continue
        if not args.yes:
            hint = "[Y/n]" if extra.default_yes else "[y/N]"
            answer = ask(f"Apply to {extra.where}? {hint} ").strip().lower()
            if answer not in {"y", "yes"} and not (extra.default_yes and answer == ""):
                print("Skipped; nothing else was changed.")
                continue
        try:
            print(extra.apply())
        except Exception as exc:
            print(f"Could not apply: {exc}", file=sys.stderr)
            raise SystemExit(1) from None


# Account commands work from anywhere; everything else works on a workspace folder.
ACCOUNT_COMMANDS = frozenset({"login", "logout", "whoami", "update"})
# No passive update notice: the MCP server's stdout is the protocol stream, and
# `update` reports versions itself.
NO_UPDATE_NOTICE = frozenset({"mcp", "update", "draft", "project"})


# Used when the current folder can't be written (a shell sitting in "/", a
# read-only mount) and no --workspace was given.
DEFAULT_WORKSPACE = Path.home() / "migrations"  # the folder the installer creates


def resolve_workspace(args) -> None:
    """Pick the folder the file tools work in; never a read-only one.

    Running from "/" on macOS made setup try to create "/.netconverter" on the
    read-only system volume and crash with a traceback.
    """
    explicit = args.workspace is not None
    args.workspace = args.workspace or "."
    if args.command in ACCOUNT_COMMANDS:
        return
    try:
        root = Path(args.workspace).resolve(strict=True)
    except FileNotFoundError:
        return  # workspace_settings reports a deleted folder
    if os.access(root, os.W_OK):
        return
    if explicit:
        raise CommandError(
            f"netconverter: the folder {str(root)!r} is not writable. "
            f"Pass --workspace with a folder you own, for example --workspace {DEFAULT_WORKSPACE}.",
            EXIT_INPUT,
        )
    DEFAULT_WORKSPACE.mkdir(mode=0o700, parents=True, exist_ok=True)
    print(
        f"netconverter: {root} is not writable, so {DEFAULT_WORKSPACE} is the workspace. "
        "cd to your configuration folder or pass --workspace to use another.",
        file=sys.stderr,
    )
    args.workspace = str(DEFAULT_WORKSPACE)


def workspace_settings(args) -> dict:
    """Saved folder settings; a missing folder is a clear message, never a traceback.

    A shell can sit in a folder that was deleted underneath it (a removed git
    worktree), where even resolving "." fails.
    """
    try:
        return load_settings(args.workspace)
    except FileNotFoundError:
        if args.command in ACCOUNT_COMMANDS:
            return {}
        raise CommandError(
            f"netconverter: the folder {args.workspace!r} no longer exists (was it deleted?). "
            "cd to your configuration folder and run the command again.",
            EXIT_INPUT,
        ) from None


class _Parser(argparse.ArgumentParser):
    """argparse with a "Did you mean" for a mistyped command or choice (#8)."""

    def error(self, message):
        match = re.search(r"argument (.+?): invalid choice: '([^']*)'", message)
        action = match and next((a for a in self._actions if a.choices and match.group(1) in
                                 {a.metavar, a.dest, "/".join(a.option_strings)}), None)
        if not action:
            super().error(message)
        value, choices = match.group(2), [str(c) for c in action.choices]
        close = difflib.get_close_matches(value, choices, n=1, cutoff=0.6)
        hint = f" Did you mean '{close[0]}'?" if close else ""
        if isinstance(action, argparse._SubParsersAction):
            text = f"Unknown command '{value}'.{hint} Run `{self.prog} --help` for the list."
        else:
            text = f"Invalid value '{value}' for {match.group(1)}.{hint} Choose from: {', '.join(choices)}."
        self.exit(EXIT_USAGE, f"netconverter: {text}\n")


OPTIONS_HELP = ("job settings as a JSON object, for example "
                f"{OPTIONS_EXAMPLE.removeprefix('--options ')}; "
                "a YAML v2 decisions file goes in as {\"yaml_v2\": \"<YAML text>\"} (convert only)")


def parser():
    from . import __version__

    p = _Parser(prog="netconverter",
                description="Migrate, validate and optimize network configurations from the folder that holds them. "
                            "Run without a command for the full-screen app.",
                epilog="Global options go before the command: netconverter --workspace DIR convert FILE ... "
                       "Exit codes and examples: docs/COMMANDS.md.")
    p.add_argument("--version", action="version", version=f"netconverter-cli {__version__}",
                   help="print the client version and exit")
    p.add_argument("--workspace", default=None, metavar="DIR",
                   help="configuration folder to work in (default: the current folder)")
    p.add_argument("--server", default=os.getenv("NETCONVERTER_URL"), metavar="URL",
                   help="NetConverter API URL (default: NETCONVERTER_URL, else production)")
    p.add_argument(
        "--provider",
        choices=["openai", "anthropic", "gemini", "ollama"],
        default=os.getenv("NETCONVERTER_PROVIDER"),
        metavar="NAME",
        help="optional model provider for plain-language questions: openai, anthropic, gemini or ollama",
    )
    p.add_argument("--model", default=os.getenv("NETCONVERTER_MODEL"), metavar="ID",
                   help="exact model ID for --provider (default: NETCONVERTER_MODEL)")
    subs = p.add_subparsers(dest="command", metavar="COMMAND", title="commands")
    subs.add_parser("run", help="(advanced) open the full-screen app; the same as no command")
    lic = subs.add_parser("license", help="read and accept the client license")
    lic.add_argument("license_action", nargs="?", choices=["show", "accept", "status"],
                     help="show the full text, accept it, or print the acceptance status")
    lic.add_argument("--yes", action="store_true", help="accept without a prompt (scripts)")
    tour = subs.add_parser("walkthrough", help="a short guided tour of the client and its integrations")
    tour.add_argument("step", nargs="?", type=int, help="show one step (1-7)")
    tour.add_argument("--all", action="store_true", help="print every step without pausing")
    login = subs.add_parser("login", help="store an API key, or sign in with --clerk")
    method = login.add_mutually_exclusive_group()
    method.add_argument("--clerk", action="store_true", help="sign in with your NetConverter account (browser)")
    method.add_argument("--key", action="store_true", help="store an API key (the default)")
    login.add_argument("--device", action="store_true", help="Clerk sign-in with a device code (headless machines)")
    logout = subs.add_parser("logout", help="remove the Clerk sign-in from the OS credential store")
    logout.add_argument("--all", action="store_true", help="also remove the stored API key for this server")
    subs.add_parser("whoami", help="show the signed-in account (never prints tokens)")
    mcp = subs.add_parser("mcp", help="run the local stdio MCP server for AI clients")
    mcp.add_argument("--auth", choices=list(MCP_AUTH_MODES), default=mcp_auth_default(),
                     help="credential: auto (the sign-in, else an API key), clerk or key; "
                          "default from NETCONVERTER_MCP_AUTH, else NETCONVERTER_AUTH")
    mcp.add_argument("--mcp-url", default=os.getenv("NETCONVERTER_MCP_URL"), metavar="URL",
                     help="NetConverter MCP endpoint for the remote tools (default: derived from --server)")
    mcp.add_argument("--no-remote", action="store_true", help="serve only the local file tools")
    mcp.add_argument("--guided", action="store_true",
                     help="revisioned draft tools with human approval; requires server capability")
    mcp.add_argument("--level", "--view", dest="view", choices=list(MCP_VIEWS), default=mcp_view_default(),
                     metavar="LEVEL",
                     help="lower this folder's exposure level for this process: none, masked, selected or "
                          "full (strict = masked); never above `netconverter privacy level`; "
                          "default from NETCONVERTER_MCP_VIEW")
    mcp.add_argument("--strict", dest="view", action="store_const", const="strict",
                     help="at most masked (the strict view)")
    mcp.add_argument("--full", dest="view", action="store_const", const="full",
                     help="up to full, when this folder's level is full")
    mcp.add_argument("--workspace", default=argparse.SUPPRESS, help="folder the file tools may read and write")
    from .connect import CLIENTS as _AI_CLIENTS
    connect = subs.add_parser(
        "connect", help="wire an AI assistant (Claude, Cursor, Gemini, ChatGPT, …) to this folder")
    connect.add_argument("client", nargs="?", choices=list(_AI_CLIENTS), metavar="CLIENT",
                         help="assistant to connect: " + ", ".join(_AI_CLIENTS) + " (omit to list them)")
    connect.add_argument("--all", action="store_true", help="connect every AI assistant found on this computer")
    connect.add_argument("--print", action="store_true", dest="print_only", help="show the change without applying it")
    connect.add_argument("--yes", action="store_true", help="apply without asking (scripts)")
    connect.add_argument("--remove", action="store_true", help="remove the client's netconverter entry (openclaw)")
    update = subs.add_parser("update", help="upgrade from PyPI, or install the latest verified release from GitHub")
    update.add_argument("--check", action="store_true", help="only report whether a newer release exists")
    update.add_argument("--yes", action="store_true", help="install without asking")
    update.add_argument("--json", action="store_true", help="with --check: print the result as JSON")
    subs.add_parser("capabilities", help="vendors, conversion paths and limits for your credential")
    from .draft_cli import add_parser as add_draft_parser
    add_draft_parser(subs)
    from .project_cli import add_parser as add_project_parser
    add_project_parser(subs)
    from .privacy_cli import add_parser as add_privacy_parser
    add_privacy_parser(subs)
    subs.add_parser("setup", help="first-run setup: connect to NetConverter and, optionally, a model")
    subs.add_parser("jobs", help="list your NetConverter jobs")
    from .one_shot import add_flags as add_output_flags
    resume = subs.add_parser("resume", help="follow a job (or finish an interrupted submission)")
    resume.add_argument("job_id", nargs="?", help="job to follow (default: the folder's active job)")
    add_output_flags(resume)
    for name, summary in (("validate", "check a configuration: readiness, findings, parse gaps"),
                          ("analyze", "(advanced) the same as validate"),
                          ("optimize", "cleanup and optimization findings for a configuration"),
                          ("convert", "migrate a configuration to another vendor (--to)")):
        sub = subs.add_parser(name, help=summary)
        sub.add_argument("file", help="configuration file inside the workspace folder")
        sub.add_argument("--vendor", metavar="CODE",
                         help="source vendor code, e.g. fortinet or cisco_asa (`netconverter capabilities` lists them)")
        if name == "convert":
            sub.add_argument("--to", dest="target", metavar="CODE",
                             help="target vendor code, e.g. palo_alto_xml")
        sub.add_argument("--options", default="{}", metavar="JSON", help=OPTIONS_HELP)
        add_output_flags(sub)
    ask = subs.add_parser("ask", help="one plain-language question about the active job (needs --provider)")
    ask.add_argument("question", help="the question, in quotes")
    query = subs.add_parser("query", help="a structured question about the active job (nat, routes, flow, …)")
    query.add_argument("operation", help="unused_objects, unparsed_lines, routes, interfaces, policy, nat, dependencies or flow")
    query.add_argument("--arguments", default="{}", metavar="JSON",
                       help="""parameters as a JSON object, e.g. '{"object_name":"NAME"}' for dependencies""")
    subs.add_parser("download", help="save the active job's outputs beside its source, hash-verified")
    subs.add_parser("allowance", help="your remaining allowance and limits (the same as capabilities)")
    subs.add_parser("model-test", help="(advanced) check that --provider/--model can choose operations")
    plain = subs.add_parser("plain", help="a line prompt instead of the full-screen app")
    plain.add_argument("instruction", nargs="?", help="run one app command (e.g. '/jobs') and exit")
    return p


def _stderr(message: str) -> None:
    print(message if message.startswith("netconverter") else f"netconverter: {message}", file=sys.stderr)


def main(argv=None):
    """Errors go to stderr with a distinct exit code (docs/COMMANDS.md § Exit codes)."""
    try:  # JSON keeps "→" (#28); a legacy code page shows an escape instead of failing
        sys.stdout.reconfigure(errors="backslashreplace")
    except (AttributeError, ValueError):
        pass
    try:
        _main(argv)
    except CommandError as exc:
        _stderr(exc.message)
        raise  # a SystemExit whose code is the exit status; str() keeps the message
    except KeyringLocked:
        _stderr(KEYRING_LOCKED)
        raise SystemExit(EXIT_AUTH) from None
    except (KeyboardInterrupt, EOFError):
        print(CANCELLED, file=sys.stderr)
        raise SystemExit(EXIT_CANCELLED) from None


def _main(argv=None):
    args = parser().parse_args(argv)
    from . import license as license_
    if args.command == "license":
        raise SystemExit(license_.run(args))
    if args.command == "walkthrough":
        from . import walkthrough
        raise SystemExit(walkthrough.run(args))
    if args.command == "mcp" and not license_.accepted():
        # An AI client starts the bridge with no terminal to prompt in.
        license_.serve_blocked_mcp()
        return
    license_.ensure(args.command, interactive=sys.stdin.isatty() and sys.stdout.isatty())
    resolve_workspace(args)
    if args.command == "privacy":  # terminal only: never reachable from the bridge (#13)
        from .privacy_cli import run as run_privacy

        raise SystemExit(run_privacy(args))
    if args.command == "update":
        from . import update

        raise SystemExit(update.run(args))
    if args.command not in NO_UPDATE_NOTICE:
        from . import update

        update.notify()  # stderr, once a day, never blocks or fails the command
    settings = workspace_settings(args)
    saved_server = settings.get("server")
    if not args.server and saved_server and not workspace_server_trusted(saved_server):
        # connection.json travels with a shared or cloned folder: it must not be able
        # to point any credential (an API key, NETCONVERTER_API_KEY) at a foreign host.
        raise CommandError(
            f"netconverter: this folder's saved server {saved_server!r} is not a trusted NetConverter "
            "host. Pass --server explicitly, or set NETCONVERTER_TRUSTED_HOSTS to trust it.",
            EXIT_USAGE,
        )
    args.server = args.server or saved_server or DEFAULT_BASE
    args.provider = args.provider or settings.get("provider")
    args.model = args.model or settings.get("model")
    if args.command == "login" and args.key and args.device:
        raise CommandError("--device applies to Clerk sign-in; omit --key", EXIT_USAGE)
    if args.command == "login" and (args.clerk or args.device or (not args.key and clerk_preferred(settings))):
        clerk_login(args, settings)
        return
    if args.command == "logout":
        logout(args)
        return
    if args.command == "whoami":
        whoami(args)
        return
    if args.command == "mcp":
        run_mcp(args)
        return
    if args.command == "connect":
        run_connect(args)
        return
    if args.command in {"draft", "project"}:
        if args.command == "project":
            from .project_cli import run as run_draft
        else:
            from .draft_cli import run as run_draft

        try:
            credential = rest_credential(args.server, settings, interactive=False)
        except SystemExit:
            print(json.dumps({"schema_version": "1", "ok": False, "error": {
                "code": "access_denied",
                "message": "Sign in or configure a credential for this trusted server before using drafts."
            }}))
            raise SystemExit(1) from None
        result = run_draft(args, credential)
        print(json.dumps(result, sort_keys=True, ensure_ascii=False))
        if not result["ok"]:
            raise SystemExit(1)
        return
    if args.command == "login":
        key = getpass.getpass("NetConverter API key (hidden): ").strip()
        kind, _ = detect_profile(key, args.server)
        stored = save_secret(account(args.server), key)
        from .workspace import Workspace
        # remembering the server is optional; "/" and other read-only folders skip it
        if Path(args.workspace).is_dir() and os.access(args.workspace, os.W_OK):
            workspace = Workspace(args.workspace)
            workspace._inside(workspace.state_dir).mkdir(mode=0o700, exist_ok=True)
            workspace._atomic_replace(workspace.state_dir / "connection.json", json.dumps({**settings, "server": args.server}).encode())
        print(
            json.dumps(
                {
                    "profile": "full_api" if kind == "external" else "terminal_quick",
                    "credential_storage": "OS credential store"
                    if stored
                    else "unavailable; enter key for each session",
                }
            )
        )
        return
    provider = None
    client = None
    options = check_submission(args) if args.command in SUBMIT_COMMANDS else None
    try:
        if args.command == "setup" or (args.command in (None, "run") and not settings):
            client, provider = configure(args.workspace, {"server": args.server, "provider": args.provider, "model": args.model})
            from .tui import Terminal
            Terminal(Controller(Path(args.workspace), client, provider,
                                remote=lambda: remote_for(args.server, client.credential))).run(mouse=False)
            return
        if args.provider:
            provider = Provider(
                args.provider,
                args.model,
                "" if args.provider == "ollama" else get_secret(args.provider),
            )
        if args.command == "model-test":
            if not provider:
                raise ValueError("Choose --provider and --model")
            result = provider.select("Find unused objects")
            print(
                json.dumps(
                    {
                        "provider": provider.name,
                        "model": provider.model,
                        "compatible": result == "unused_objects",
                    }
                )
            )
            return
        try:
            credential = rest_credential(args.server, settings)
        except CommandError:
            if args.command in SUBMIT_COMMANDS and not args.vendor:  # the usage problem comes first
                raise CommandError(VENDOR_REQUIRED + " `netconverter capabilities` lists the codes once "
                                   "you are signed in.", EXIT_USAGE) from None
            raise
        client, kind = open_client(credential, args.server)
        c = Controller(Path(args.workspace), client, provider, kind=kind,
                       remote=lambda: remote_for(args.server, credential))
        if args.command in (None, "run"):
            from .tui import Terminal

            Terminal(c).run(mouse=False)
            return
        if args.command == "capabilities":
            result = c.capabilities()
        elif args.command in {"validate", "analyze", "optimize", "convert"}:
            c.capabilities()
            check_source_vendor(args.vendor, c.catalog)  # before anything is uploaded (#22)
            c.select(args.file, args.vendor)
            if getattr(args, "target", None):
                options["target_vendor"] = args.target
            result = c.submit("validate" if args.command == "analyze" else args.command, options)
        elif args.command == "resume":
            result = c.resume(args.job_id)
        elif args.command == "jobs":
            result = client.jobs()
        elif args.command == "query":
            result = c.query(args.operation, json.loads(args.arguments))
        elif args.command == "ask":
            result = execute(c, args.question)
        elif args.command == "download":
            result = c.download()
        elif args.command == "allowance":
            result = c.capabilities()
        elif args.command == "plain":
            if args.instruction:
                result = execute(c, args.instruction)
            else:
                while True:
                    try:
                        line = input("netconverter> ")
                    except EOFError:
                        break
                    if line in {"/quit", "/exit"}:
                        break
                    try:
                        print(json.dumps(execute(c, line), indent=2, default=str, ensure_ascii=False))
                    except Exception:
                        print(
                            "Command failed; use /help. No diagnostic payload was saved."
                        )
                return
        from .one_shot import SUMMARY_COMMANDS, render
        if args.command in SUMMARY_COMMANDS:  # a plain summary; --json for the raw response (#7)
            print(render(c, args, result))
        else:
            print(json.dumps(result, indent=2, default=str, ensure_ascii=False))
    except ProviderError as exc:
        raise CommandError(str(exc), EXIT_FAILURE) from None
    except OptionsError as exc:
        raise CommandError(str(exc), EXIT_INPUT) from None
    except APIError as exc:
        text = api_error_message(exc) if exc.status in (401, 403) else str(exc)
        if exc.detail:
            text += "\n" + json.dumps(exc.detail, ensure_ascii=False)
        raise CommandError(text, api_exit_code(exc)) from None
    except KeyringLocked:
        raise
    except ClerkError as exc:
        raise CommandError(str(exc) or SIGNED_OUT, EXIT_AUTH) from None
    except ValueError as exc:  # WorkspaceError and other refused input: the reason, verbatim
        raise CommandError(str(exc) or "Invalid input; see `netconverter --help`.", EXIT_INPUT) from None
    except RuntimeError as exc:
        raise CommandError(str(exc) or "The operation failed; see `netconverter --help`.", EXIT_FAILURE) from None
    finally:
        if client:
            client.close()
        if provider:
            provider.close()


if __name__ == "__main__":
    main()
