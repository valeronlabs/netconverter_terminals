"""Independent terminal executable; importing it never imports appliance code."""

import argparse
import getpass
import json
import os
import sys
from pathlib import Path
from .api import Client, DEFAULT_BASE, APIError
from .backend import detect_profile, open_client
from .credentials import get_secret, keyring_available, save_secret
from .controller import Controller
from .providers import Provider, ProviderError
from .commands import execute
from .setup import configure, load_settings, account
from .remote_mcp import DEFAULT_MCP_URL


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


def rest_credential(server, settings):
    """The credential plain commands use: a stored key, else the sign-in.

    NETCONVERTER_AUTH=key|clerk (the user's environment, never the workspace's
    connection.json) forces one; unset, a stored key wins and the sign-in is
    used only for a trusted NetConverter host.
    """
    mode = os.getenv("NETCONVERTER_AUTH", "auto")
    if mode == "clerk":
        if not clerk_allowed(server):
            raise SystemExit(f"Refusing to send your NetConverter sign-in to {server}: not a trusted "
                             "NetConverter host (set NETCONVERTER_TRUSTED_HOSTS to trust it explicitly)")
        session = _clerk_session()
        if session is None:
            raise SystemExit("Not signed in; run `netconverter login --clerk`")
        return session
    if mode == "key":
        return get_secret(account(server))
    key = get_secret(account(server), prompt=False)
    if key:
        return key
    if clerk_allowed(server):
        session = _clerk_session()
        if session is not None:
            return session
    if not keyring_available():
        return get_secret(account(server))  # no credential store: a memory-only key prompt
    raise SystemExit(f"No NetConverter credential for {server}. Run `netconverter login --clerk` to "
                     "sign in with your account, or `netconverter login` to store an API key.")


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
                      "credential_storage": "OS credential store"}))


def logout(args):
    from .clerk import ClerkSession
    from .credentials import delete_secret

    result = {"clerk_signed_out": ClerkSession().revoke_and_clear()}
    if args.all:
        result["api_key_removed"] = delete_secret(account(args.server))
    print(json.dumps(result))


def whoami(args):
    from .clerk import ClerkError, profile_summary

    out = {"server": args.server, "api_key_stored": bool(get_secret(account(args.server), prompt=False))}
    session = _clerk_session()
    if session is None:
        out["clerk"] = None
    else:
        try:
            out["clerk"] = {"signed_in": True, **profile_summary(session.userinfo())}
        except ClerkError as exc:
            out["clerk"] = {"signed_in": False, "message": str(exc)}
    print(json.dumps(out, indent=2))


def run_mcp(args):
    from .mcp_server import Bridge, run_stdio
    from .remote_mcp import RemoteMCP
    from . import __version__

    key = get_secret(account(args.server), prompt=False) if args.auth in ("auto", "key") else ""
    session = _clerk_session() if args.auth in ("auto", "clerk") else None
    key = key or None
    mcp_url = args.mcp_url or mcp_url_for(args.server)
    # The Clerk token goes only to trusted NetConverter hosts, per destination.
    rest_session = session if session is not None and clerk_allowed(args.server) else None
    remote_session = session if session is not None and clerk_allowed(mcp_url) else None
    if session is not None and (rest_session is None or remote_session is None):
        print("netconverter: your sign-in is only sent to trusted NetConverter hosts; "
              "an untrusted server or MCP URL will not receive it", file=sys.stderr)
    if args.auth == "auto":
        # Today: API keys reach the REST API; Clerk tokens reach remote MCP.
        rest, remote_credential = (key or rest_session), (remote_session or key)
    else:
        rest, remote_credential = (key, key) if args.auth == "key" else (rest_session, remote_session)
    remote = None
    if remote_credential is not None and not args.no_remote:
        remote = RemoteMCP(mcp_url, remote_credential, client_version=__version__)
    try:
        run_stdio(Bridge(args.workspace, args.server, rest, remote, strict=getattr(args, "strict", False)))
    finally:
        if remote:
            remote.close()


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
    from .connect import CLIENTS, plan

    change = plan(args.client, root)
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
NO_UPDATE_NOTICE = frozenset({"mcp", "update"})


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
        raise SystemExit(
            f"netconverter: the folder {args.workspace!r} no longer exists (was it deleted?). "
            "cd to your configuration folder and run the command again."
        ) from None


def parser():
    from . import __version__

    p = argparse.ArgumentParser(prog="netconverter")
    p.add_argument("--version", action="version", version=f"netconverter-cli {__version__}")
    p.add_argument("--workspace", default=".")
    p.add_argument("--server", default=os.getenv("NETCONVERTER_URL"))
    p.add_argument(
        "--provider",
        choices=["openai", "anthropic", "gemini", "ollama"],
        default=os.getenv("NETCONVERTER_PROVIDER"),
    )
    p.add_argument("--model", default=os.getenv("NETCONVERTER_MODEL"))
    subs = p.add_subparsers(dest="command")
    subs.add_parser("run")
    login = subs.add_parser("login", help="store an API key, or sign in with --clerk")
    method = login.add_mutually_exclusive_group()
    method.add_argument("--clerk", action="store_true", help="sign in with your NetConverter account (browser)")
    method.add_argument("--key", action="store_true", help="store an API key (the default)")
    login.add_argument("--device", action="store_true", help="Clerk sign-in with a device code (headless machines)")
    logout = subs.add_parser("logout", help="remove the Clerk sign-in from the OS credential store")
    logout.add_argument("--all", action="store_true", help="also remove the stored API key for this server")
    subs.add_parser("whoami", help="show the signed-in account (never prints tokens)")
    mcp = subs.add_parser("mcp", help="run the local stdio MCP server for AI clients")
    mcp.add_argument("--auth", choices=["auto", "clerk", "key"], default=os.getenv("NETCONVERTER_MCP_AUTH", "auto"))
    mcp.add_argument("--mcp-url", default=os.getenv("NETCONVERTER_MCP_URL"))
    mcp.add_argument("--no-remote", action="store_true", help="serve only the local file tools")
    mcp.add_argument("--strict", action="store_true", default=os.getenv("NETCONVERTER_MCP_STRICT") == "1",
                     help="proxy only the strict-view remote tools (summaries, names as tokens)")
    mcp.add_argument("--workspace", default=argparse.SUPPRESS, help="folder the file tools may read and write")
    from .connect import CLIENTS as _AI_CLIENTS
    connect = subs.add_parser(
        "connect", help="wire an AI assistant (Claude, Cursor, Gemini, ChatGPT, …) to this folder")
    connect.add_argument("client", nargs="?", choices=list(_AI_CLIENTS))
    connect.add_argument("--all", action="store_true", help="connect every AI assistant found on this computer")
    connect.add_argument("--print", action="store_true", dest="print_only", help="show the change without applying it")
    connect.add_argument("--yes", action="store_true", help="apply without asking (scripts)")
    update = subs.add_parser("update", help="upgrade from PyPI, or install the latest verified release from GitHub")
    update.add_argument("--check", action="store_true", help="only report whether a newer release exists")
    update.add_argument("--yes", action="store_true", help="install without asking")
    subs.add_parser("capabilities", help="vendors, conversion paths and limits for your credential")
    subs.add_parser("setup")
    subs.add_parser("jobs")
    resume = subs.add_parser("resume")
    resume.add_argument("job_id", nargs="?")
    for name in ("validate", "analyze", "optimize", "convert"):
        sub = subs.add_parser(name)
        sub.add_argument("file")
        sub.add_argument("--vendor", required=True, help="source vendor code (see `netconverter capabilities`)")
        sub.add_argument("--to", dest="target", help="target vendor code (convert)")
        sub.add_argument("--options", default="{}")
    ask = subs.add_parser("ask")
    ask.add_argument("question")
    query = subs.add_parser("query")
    query.add_argument("operation")
    query.add_argument("--arguments", default="{}")
    subs.add_parser("download")
    subs.add_parser("allowance")
    subs.add_parser("model-test")
    plain = subs.add_parser("plain")
    plain.add_argument("instruction", nargs="?")
    return p


def main(argv=None):
    args = parser().parse_args(argv)
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
        raise SystemExit(
            f"netconverter: this folder's saved server {saved_server!r} is not a trusted NetConverter "
            "host. Pass --server explicitly, or set NETCONVERTER_TRUSTED_HOSTS to trust it."
        )
    args.server = args.server or saved_server or DEFAULT_BASE
    args.provider = args.provider or settings.get("provider")
    args.model = args.model or settings.get("model")
    if args.command == "login" and args.key and args.device:
        raise SystemExit("--device applies to Clerk sign-in; omit --key")
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
    if args.command == "login":
        key = getpass.getpass("NetConverter API key (hidden): ").strip()
        kind, _ = detect_profile(key, args.server)
        stored = save_secret(account(args.server), key)
        from .workspace import Workspace
        if Path(args.workspace).is_dir():  # remembering the server is optional
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
        credential = rest_credential(args.server, settings)
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
            c.select(args.file, args.vendor)
            options = json.loads(args.options)
            if args.target:
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
                        print(json.dumps(execute(c, line), indent=2, default=str))
                    except Exception:
                        print(
                            "Command failed; use /help. No diagnostic payload was saved."
                        )
                return
        print(json.dumps(result, indent=2, default=str))
    except ProviderError as exc:
        print(str(exc))
        raise SystemExit(1) from None
    except APIError as exc:
        print(str(exc))
        if exc.detail:
            print(json.dumps(exc.detail))
        raise SystemExit(1) from None
    except (ValueError, RuntimeError):
        print("Invalid or unavailable operation; use --help or guided plain mode.")
        raise SystemExit(1) from None
    finally:
        if client:
            client.close()
        if provider:
            provider.close()


if __name__ == "__main__":
    main()
