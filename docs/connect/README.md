# Connect your AI assistant to NetConverter

NetConverter reaches your AI assistant in one of two ways. Pick the one your assistant supports.

| Way | What your AI can do | Assistants |
|---|---|---|
| **Terminal bridge** (`netconverter mcp`, runs on your computer) | Everything below, **plus submit** configurations for conversion, validation and optimization. The bridge uploads the file from disk; the configuration never passes through the model. | Claude Desktop, Claude Code, Cursor, Gemini CLI, Codex CLI, VS Code, Devin Desktop / Windsurf, LM Studio, OpenClaw |
| **Remote connector** (`https://api.netconverter.ai/mcp/v1`) | Read your jobs, verdicts, evidence and reports, your account, and the NetConverter migration knowledge base. No file submission. | claude.ai (web, mobile, Desktop chat), ChatGPT |

Both need a NetConverter account with **MCP access enabled** by your administrator
(Admin portal → MCP Management). Sign in with that account when asked.

## Guides

- **[Getting access](getting-access.md)** — new users and administrators start here
- [claude.ai, Claude Desktop chat and the Claude mobile app](claude-ai.md) — remote connector
- [ChatGPT](chatgpt.md) — remote connector
- [Claude Desktop](claude-desktop.md) — terminal bridge
- [Claude Code](claude-code.md) — terminal bridge
- [Cursor, Gemini CLI, Codex CLI, VS Code, Devin Desktop / Windsurf, LM Studio](other-assistants.md) — terminal bridge
- [Compatibility matrix](compatibility.md): each client's config path and format, the vendor doc checked, and live-test status
- [OpenClaw](openclaw.md) — terminal bridge, through `openclaw mcp`

## Fastest path (terminal bridge)

```sh
curl -LsSf https://netconverter.ai/install.sh | sh          # macOS / Linux
```
```powershell
irm https://netconverter.ai/install.ps1 | iex                # Windows (PowerShell)
```

The installer installs the CLI, signs you in and runs `connect --all` for `~/migrations`.
Then restart each assistant. `netconverter connect` shows the exact change and asks
before writing; every JSON config it edits keeps a `.bak`. `netconverter update` keeps
the CLI current.

Already installed? The same steps by hand:

```sh
netconverter login --clerk          # sign in once
netconverter connect                # see which assistants are found and connected
netconverter connect --all          # connect every assistant found on this computer
```

Manual install: `uv tool install --python 3.12 netconverter-cli` ([uv](https://docs.astral.sh/uv)),
or the wheel from the [latest release](https://github.com/valeronlabs/netconverter_terminals/releases/latest)
— see [getting access](getting-access.md).

## Check that it works

Ask your assistant: **"What NetConverter tools do you have? Show my NetConverter account."**
It should list tools such as `list_jobs`, `get_job_brief` and `kb_search`, and
`get_account` should return your plan, view mode and today's remaining budget.

| Symptom | Fix |
|---|---|
| No NetConverter tools | Fully quit and reopen the assistant (MCP servers load at startup). Run `netconverter connect` to confirm it is connected. |
| `mcp_not_granted` / "not enabled for this account" | Ask your NetConverter administrator to grant MCP access to your user or organization. |
| Sign-in loops or fails (remote connector) | Check the OAuth Client ID in the connector's advanced settings matches the guide, and sign in with your NetConverter account. |
| Names appear as `<name:…>` | Your account uses **strict view**: configuration names are tokenised on purpose. |
| `keyring_unreachable` (Linux: Codex, Cursor CLI, OpenClaw) | The assistant started the bridge without `DBUS_SESSION_BUS_ADDRESS`, so your sign-in in the OS keyring is invisible. The bridge looks for `$XDG_RUNTIME_DIR/bus` and `/run/user/<uid>/bus` itself; if neither exists, set `DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/<uid>/bus` (Codex `env_vars`; Cursor/OpenClaw `env`) or `NETCONVERTER_API_KEY` in the assistant's MCP server config and restart it. |

Privacy details: [PRIVACY.md](../PRIVACY.md).
