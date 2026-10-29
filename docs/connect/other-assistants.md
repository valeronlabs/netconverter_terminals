# Cursor, Gemini CLI, Codex CLI, VS Code, Devin Desktop / Windsurf, LM Studio

All of these run the terminal bridge on your computer, so they can submit
configurations as well as read results.

The [installer](getting-access.md) (`curl -LsSf https://netconverter.ai/install.sh | sh`, or
`irm https://netconverter.ai/install.ps1 | iex` on Windows) installs the CLI and connects all
of them at once. Already installed, or installed by hand
(`uv tool install --python 3.12 netconverter-cli`):

```sh
netconverter login --clerk
netconverter --workspace ~/migrations connect --all     # every assistant found here
# or one at a time:
netconverter --workspace ~/migrations connect <client>
```

| Client key | Assistant | What `connect` changes | Load the tools |
|---|---|---|---|
| `cursor` | Cursor | `~/.cursor/mcp.json` | Reload Cursor |
| `gemini` | Gemini CLI | `~/.gemini/settings.json`, with an `env` block | Trust the folder, restart `gemini`, then `/mcp` |
| `codex` | Codex CLI | appends `[mcp_servers.netconverter]` (with `env_vars`) to `~/.codex/config.toml` | Restart Codex |
| `vscode` | VS Code | this folder's `.vscode/mcp.json` | MCP: List Servers → start `netconverter` |
| `devin` | Devin Desktop (formerly Windsurf) and Devin CLI | `~/.config/devin/mcp_config.json` | Restart; `devin mcp list` |
| `windsurf` | Windsurf, legacy Cascade agent | `~/.codeium/windsurf/mcp_config.json` | Cascade → MCP → refresh, or restart |
| `lmstudio` | LM Studio | `~/.lmstudio/mcp.json` | Restart; use a tool-capable model |

Every JSON file keeps a `.bak` and every other key is preserved. `--print` shows the
change without writing; `--yes` applies without asking.

**Gemini CLI:** Gemini removes environment variables whose names contain KEY, TOKEN, AUTH,
SECRET, PASSWORD or CREDENTIAL before it starts an MCP server, unless the server's `env`
lists them. So `connect gemini` writes `"NETCONVERTER_API_KEY": "$NETCONVERTER_API_KEY"`
and similar references for the bridge's variables. These are references only; no value
is written. Gemini also starts **no** MCP server, user-level ones included, in a folder
you have not trusted. Trust the folder you run `gemini` in when it asks, or with
`/permissions` (or `gemini trust`).

**Codex CLI** starts MCP servers with a cleared environment; the `env_vars` line forwards the
NetConverter variables and `DBUS_SESSION_BUS_ADDRESS` from the environment you start Codex in.

Paths and formats were checked against each vendor's docs on 2026-10-29: see the
[compatibility matrix](compatibility.md).

The Gemini **web/mobile app** and other chat apps that cannot start a local program are
not supported by the bridge; use one of the assistants above, or a
[remote-connector](README.md) assistant for read-only access.
