"""Independent terminal executable; importing it never imports appliance code."""

import argparse
import getpass
import json
import os
from pathlib import Path
from .api import Client, DEFAULT_BASE, APIError
from .credentials import get_secret, save_secret
from .controller import Controller
from .providers import Provider
from .commands import execute
from .setup import configure, load_settings, account


def parser():
    p = argparse.ArgumentParser(prog="netconverter")
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
    subs.add_parser("login")
    subs.add_parser("setup")
    subs.add_parser("jobs")
    resume = subs.add_parser("resume")
    resume.add_argument("job_id", nargs="?")
    for name in ("analyze", "optimize", "convert"):
        sub = subs.add_parser(name)
        sub.add_argument("file")
        sub.add_argument("--vendor", default="cisco_asa")
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
    settings = load_settings(args.workspace)
    args.server = args.server or settings.get("server") or DEFAULT_BASE
    args.provider = args.provider or settings.get("provider")
    args.model = args.model or settings.get("model")
    if args.command == "login":
        key = getpass.getpass("NetConverter pilot key (hidden): ").strip()
        client = Client(key, args.server)
        try:
            caps = client.capabilities()
        finally:
            client.close()
        stored = save_secret(account(args.server), key)
        from .workspace import Workspace
        workspace = Workspace(args.workspace)
        workspace._inside(workspace.state_dir).mkdir(mode=0o700, exist_ok=True)
        workspace._atomic_replace(workspace.state_dir / "connection.json", json.dumps({**settings, "server": args.server}).encode())
        print(
            json.dumps(
                {
                    "profile": caps["profile"],
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
            Terminal(Controller(Path(args.workspace), client, provider)).run()
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
        client = Client(get_secret(account(args.server)), args.server)
        c = Controller(Path(args.workspace), client, provider)
        if args.command in (None, "run"):
            from .tui import Terminal

            Terminal(c).run()
            return
        if args.command in {"analyze", "optimize", "convert"}:
            c.select(args.file, args.vendor)
            result = c.submit(args.command, json.loads(args.options))
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
