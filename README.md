# NetConverter CLI

<!-- mcp-name: ai.netconverter/netconverter -->

**Migrate, validate and optimize network configurations from the folder that holds them — and let your own AI assistant do it too, without the configuration ever passing through the model.**

NetConverter — by ValeronLabs LLC.

```text
◆ NetConverter  v0.4.4                      ● Server   ◆ Bridge claude-code · 2m ago
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

Development preview: [revisioned drafts and guided MCP](docs/guided-workflows.md)
adds an opt-in client contract for manual YAML, reviewed migration preparation,
job status and verified result downloads.
It requires explicit server support and is not enabled by an ordinary MCP connection.

## Start here

One line installs everything (uv, the CLI from PyPI), signs you in and connects
your AI assistants to `~/migrations`:

```sh
curl -LsSf https://netconverter.ai/install.sh | sh              # macOS / Linux
```

```powershell
irm https://netconverter.ai/install.ps1 | iex                    # Windows PowerShell
```

Options: `--yes` (no prompts, for IT/MDM), `--no-connect`, `--workspace PATH`
(`curl … | sh -s -- --yes`; PowerShell: `-Yes -NoConnect -Workspace PATH`, see
[scripts/install.ps1](scripts/install.ps1)). Running it again only does what is missing.

Or by hand:

```sh
# 1. Install (Python 3.12+ via uv: https://docs.astral.sh/uv)
uv tool install --python 3.12 netconverter-cli

# 2. Sign in once
netconverter login --clerk          # your NetConverter account, in the browser
#    or: netconverter login          # paste an API key at a hidden prompt

# 3. Work in the folder that holds your configs
cd ~/migrations && netconverter
```

Upgrading from `netconverter-terminal` 0.1.x: `uv tool uninstall netconverter-terminal`
first. Saved keys and sign-ins carry over (Keychain service **NetConverter Terminal**).

Full walkthrough: [Quick start](QUICK_START.md).

A YAML v2 decisions file (zone and interface mappings) rides along with a conversion:
`netconverter convert edge.cfg --vendor fortinet --to palo_alto_xml --options "$(jq -Rs '{yaml_v2: .}' decisions.yaml)"`,
or inline as `--options '{"yaml_v2": {...}}'`; see [docs/COMMANDS.md](docs/COMMANDS.md#yaml-v2-decisions-yaml_v2).

## Use it from your AI

Step-by-step guides for every assistant (Claude, ChatGPT, Cursor, Gemini CLI, Codex …):
[docs/connect](docs/connect/README.md).

```sh
netconverter connect claude-code    # or claude-desktop, cursor, vscode, codex, gemini, devin, windsurf, lmstudio
netconverter connect --all          # every assistant found on this computer
netconverter connect chatgpt        # ChatGPT / claude.ai: remote-connector setup steps
```

`connect` shows the exact change it will make and asks before applying it
(Claude Code through its own `claude mcp add`; JSON files keep a `.bak`). For
Claude Code it then offers a `Read` deny rule for the folder, so the assistant
works on your configurations only through the bridge.
Then ask your assistant, for example: *"Validate edge-fw.conf and tell me what it finds,"*
*"Convert it to Palo Alto XML,"* *"Can WEB reach DB on tcp/1433?"*

Bridge tools: `submit_file`, `job_status`, `wait_for_job`, `account`, `download`,
plus an allowlist of NetConverter's read-only tools (reports, evidence, NAT, flows,
knowledge base). What the assistant sees is this folder's **exposure level**
(`netconverter privacy level none|masked|selected|full`, default **masked**: the strict view,
names as tokens, addresses masked, no configuration content); secrets are removed at every
level, and raising the level needs a confirmation typed in a terminal (docs/PRIVACY.md).
`netconverter privacy apply --client claude-code` (also cursor, gemini; codex and openclaw
print the settings) keeps the assistant's own file tools out of the folder. Job `options` from an assistant pass an
allowlist with type checks: an unknown or reserved key (the file, vendors, job type, a
decisions document) is refused naming it, never silently sent.

**Upgrading from 0.4.x:** `--full` (or `NETCONVERTER_MCP_VIEW=full`) no longer widens the
view on its own; run `netconverter privacy level full` in a terminal for the folder. Run
`netconverter connect <assistant>` again to drop the `--strict` that 0.4.4 wrote, which would
hold the assistant at masked.

Inside the app, `/activity` and the header's **Bridge** pill show what your AI did
through the bridge — paths, sizes, SHA-256 and job IDs only.

## Stay current

`netconverter update` upgrades a PyPI install with `uv tool upgrade netconverter-cli`;
a copy installed from a release wheel gets the latest wheel after its SHA-256 is
checked (`--check` only reports). Interactive commands mention a new release at most once
a day; set `NETCONVERTER_NO_UPDATE_CHECK=1` to turn that off.

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

The client is licensed for use with your NetConverter account only and may not be
redistributed ([license](LICENSE)); you accept it on first run (`netconverter license`).
Versions up to 0.4.3 were MIT licensed. The license does not grant access to the
hosted service or license the server code. macOS is the exercised platform;
Windows acceptance remains pending.
