# NetConverter CLI

**Migrate, validate and optimize network configurations from the folder that holds them — and let your own AI assistant do it too, without the configuration ever passing through the model.**

NetConverter — by ValeronLabs LLC.

```text
◆ NetConverter  v0.2.0                      ● Server   ◆ Bridge claude-code · 2m ago
▍ Start
▍ /convert    Migrate a configuration to another vendor
▍ /validate   Check a configuration before migrating
▍ /optimize   Cleanup and optimization findings
▍ /activity   What your AI assistant did here
╭ What does edge-fw.conf contain? ───────────────────────────────╮
│ ▸  1  Fortinet FortiGate  · detected                            │
│    2  Cisco ASA                                                 │
╰──────────────────────────────── ↑↓ choose · 1–9 jump · Enter ───╯
```

One small client, three ways in:

| | What it is |
| --- | --- |
| `netconverter` | A keyboard-first full-screen app: pick a file, answer a few inline questions, follow the job, get verified outputs beside your source. |
| `netconverter mcp` | A local MCP bridge for Claude Code, Claude Desktop, Cursor, VS Code and Codex. Your AI passes a **file path**; the bridge reads the file and uploads it straight to NetConverter. The AI sees paths, job IDs and summaries — never the configuration. |
| `netconverter validate edge.cfg --vendor fortinet` | Plain one-shot commands that print JSON, for scripts and CI. |

## What it supports

Whatever the NetConverter server you sign in to supports — the client reads
`GET /capabilities` and builds every menu from it, so new vendors appear
without a client update. Today that is:

- **Firewalls:** Palo Alto (SET, XML, Panorama), Fortinet FortiGate, Cisco FMC (JSON);
  Cisco ASA as a source. Check Point is a source through a handoff bundle in the portal.
- **Routers and switches:** Cisco IOS-XE, Juniper JunOS (braces and set), Aruba CX;
  ArubaOS as a source.
- **Jobs:** convert, validate, optimize; follow-up questions on NAT, policy, routes,
  interfaces, unused objects, object dependencies and traffic flows.

Run `netconverter capabilities` to see exactly what your credential can do.
A 0.1.x **Terminal Quick pilot key** still works and keeps its ASA → Palo Alto
scope; the app labels it as such.

## Start here

```sh
# 1. Install (Python 3.12+ via uv)
uv tool install --python 3.12 ./netconverter_cli-0.2.2-py3-none-any.whl

# 2. Sign in once
netconverter login --clerk          # your NetConverter account, in the browser
#    or: netconverter login          # paste an API key at a hidden prompt

# 3. Work in the folder that holds your configs
cd ~/migrations && netconverter
```

Upgrading from `netconverter-terminal` 0.1.x: `uv tool uninstall netconverter-terminal`
first. Saved keys and sign-ins carry over (Keychain service **NetConverter Terminal**).

Full walkthrough: [Quick start](QUICK_START.md).

## Use it from your AI

```sh
netconverter connect claude-code    # or cursor, vscode, codex
```

`connect` shows the exact change it will make and asks before applying it
(Claude Code through its own `claude mcp add`; JSON files keep a `.bak`).
Then ask your assistant, for example: *"Validate edge-fw.conf and tell me what it finds,"*
*"Convert it to Palo Alto XML,"* *"Can WEB reach DB on tcp/1433?"*

Inside the app, `/activity` and the header's **Bridge** pill show what your AI did
through the bridge — paths, sizes, SHA-256 and job IDs only.

## Boundaries

- Configurations travel only from your workspace to NetConverter, over HTTPS.
  The bridge never returns configuration text to the AI; the server tokenizes
  addresses and removes credentials from every summary.
- The client never pushes to a device. Outputs are files you review and load.
- Downloads are hash-verified and never overwrite a file you changed.
- An optional in-app model (`/model`: Anthropic, OpenAI, Gemini or local Ollama)
  only chooses among fixed operations; it never receives configurations or results.

## Documentation

- [Quick start](QUICK_START.md) · [Commands and troubleshooting](docs/COMMANDS.md)
- [Privacy and data flow](docs/PRIVACY.md) · [Verification status](docs/VERIFICATION.md)
- [Changelog](CHANGELOG.md) · [Contributing](CONTRIBUTING.md) · [Security](SECURITY.md)

The client is [MIT licensed](LICENSE). The license does not grant access to the
hosted service or license the server code. macOS is the exercised platform;
Windows acceptance remains pending.
