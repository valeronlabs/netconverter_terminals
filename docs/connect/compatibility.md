# AI client compatibility matrix

What `netconverter connect <client>` writes for each assistant, checked against each
vendor's official documentation on **2026-10-29** (issue #14). The **Live check** column
is a tester run on a real client: cells marked *to verify* have not been run against
this release yet. A doc check proves the file location and format, not that the
client then loads the bridge.

| Client key | Assistant | Config `connect` writes | Format | Official doc checked (2026-10-29) | Doc check | Live check |
|---|---|---|---|---|---|---|
| `claude-code` | Claude Code | Runs `claude mcp add --scope user netconverter -- …` (stored in `~/.claude.json` `mcpServers`); optional read-deny rule in `~/.claude/settings.json` `permissions.deny` as `Read(//abs/path/**)` | CLI command; JSON | https://code.claude.com/docs/en/mcp · https://code.claude.com/docs/en/permissions | Matches | to verify |
| `claude-desktop` | Claude Desktop | macOS `~/Library/Application Support/Claude/claude_desktop_config.json`; Windows `%APPDATA%\Claude\claude_desktop_config.json`; Linux: not edited (beta, path undocumented; use Settings → Developer → Edit Config) | JSON `mcpServers.netconverter` `{command, args}` | https://modelcontextprotocol.io/docs/develop/connect-local-servers · https://code.claude.com/docs/en/desktop-linux | Matches on macOS/Windows; Linux beta is new, so connect prints the manual step instead | to verify |
| `cursor` | Cursor (editor and CLI `agent`) | `~/.cursor/mcp.json` | JSON `mcpServers.netconverter` `{command, args}` | https://cursor.com/docs/context/mcp · https://cursor.com/docs/cli/mcp | Matches. The CLI uses the same file | to verify |
| `vscode` | VS Code (Copilot agent mode) | This folder's `.vscode/mcp.json` | JSON `servers.netconverter` `{type: "stdio", command, args}` | https://code.visualstudio.com/docs/copilot/reference/mcp-configuration | Matches | to verify |
| `codex` | Codex CLI | Appends `[mcp_servers.netconverter]` to `~/.codex/config.toml` | TOML `command`, `args`, `env_vars` | https://developers.openai.com/codex/mcp (now redirects to learn.chatgpt.com/docs/extend/mcp) · Codex config reference | Matches. Codex clears the server's environment, so connect now writes `env_vars` to forward the NetConverter variables and `DBUS_SESSION_BUS_ADDRESS` | to verify |
| `gemini` | Gemini CLI | `~/.gemini/settings.json` | JSON `mcpServers.netconverter` `{command, args, env}` | https://geminicli.com/docs/tools/mcp-server/ · https://geminicli.com/docs/cli/trusted-folders/ | Matches. Gemini strips variables named like KEY, TOKEN, AUTH, SECRET, PASSWORD or CREDENTIAL unless they are listed in `env`, so connect now writes `"NAME": "$NAME"` references for the bridge's variables. An untrusted folder connects no MCP server; connect says so | to verify |
| `devin` | Devin Desktop (formerly Windsurf) / Devin CLI | `~/.config/devin/mcp_config.json` (`$XDG_CONFIG_HOME/devin/`; Windows `%APPDATA%\devin\`) | JSON `mcpServers.netconverter` `{command, args}` | https://docs.devin.ai/cli/extensibility/mcp/configuration · https://docs.devin.ai/desktop/devin-desktop-faq | New target: Windsurf was renamed Devin Desktop on 2026-06-02, and its default agent reads the Devin CLI file | to verify |
| `windsurf` | Windsurf (legacy Cascade) | `~/.codeium/windsurf/mcp_config.json` | JSON `mcpServers.netconverter` `{command, args}` | https://docs.windsurf.com/windsurf/cascade/mcp (redirects to docs.devin.ai/desktop/cascade/mcp) | Legacy: the current pages no longer name this file and say the Cascade config applies to the legacy agent only. Kept for older installs | to verify |
| `lmstudio` | LM Studio | `~/.lmstudio/mcp.json` (Windows `%USERPROFILE%\.lmstudio\mcp.json`) | JSON `mcpServers.netconverter` `{command, args}`, Cursor notation | https://lmstudio.ai/docs/app/mcp · https://lmstudio.ai/blog/mcp | Matches | to verify |
| `openclaw` | OpenClaw | Runs `openclaw mcp add netconverter --command … --arg …`, which writes `mcp.servers.netconverter` in `~/.openclaw/openclaw.json`; deny step in [openclaw.md](openclaw.md) | CLI command; JSON5 | https://docs.openclaw.ai/tools/mcp · https://docs.openclaw.ai/cli/mcp/registry | Matches | Passed in the tester's 2026-10-22 run (OpenClaw 2026.10.6, bridge 0.4.1); to verify for this release |

The tester's 2026-10-22 run on bridge 0.4.1 (MCP_CLIENT_COMPAT_2026-10-22) also listed all
five tools in Cursor CLI. Codex worked end to end with a local `--oss` model, and Gemini CLI
0.65.0 showed the variable stripping fixed above. Those runs predate this release's config
changes, so they are not counted as live passes here.

## Known caveats

- **Claude Desktop from the Microsoft Store (MSIX) on Windows:** community reports say
  the app may read a virtualized copy at
  `%LOCALAPPDATA%\Packages\Claude_<id>\LocalCache\Roaming\Claude\claude_desktop_config.json`.
  Meanwhile Settings → Developer → Edit Config opens the `%APPDATA%` copy that connect
  writes. If the tools don't appear, check that copy. This is not in the official docs:
  *to verify*.
- **Gemini CLI env references:** an unset variable becomes an empty string, which the
  bridge treats as unset. No value is ever written into `settings.json`, only `$NAME`.
- **Headless sign-in (encrypted credential file):** an assistant that starts the bridge
  must pass `NETCONVERTER_CREDENTIAL_PASSPHRASE` (or `…_PASSPHRASE_FILE`). Gemini and Codex
  get it through the entries above when it is set in the environment you start them from.
  Cursor, LM Studio, Devin and OpenClaw need it added to the entry's `env` by hand. See
  [PRIVACY.md](../PRIVACY.md#encrypted-credential-file-headless-machines).
- Remote connectors (`chatgpt`, `claude-ai`) are not edited by connect; see their guides.
