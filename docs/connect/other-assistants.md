# Cursor, Gemini CLI, Codex CLI, VS Code, Windsurf, LM Studio

All of these run the terminal bridge on your computer, so they can submit
configurations as well as read results.

```sh
netconverter login --clerk
netconverter --workspace ~/migrations connect --all     # every assistant found here
# or one at a time:
netconverter --workspace ~/migrations connect <client>
```

| Client key | Assistant | What `connect` changes | Load the tools |
|---|---|---|---|
| `cursor` | Cursor | `~/.cursor/mcp.json` | Reload Cursor |
| `gemini` | Gemini CLI | `~/.gemini/settings.json` | Restart `gemini`, then `/mcp` |
| `codex` | Codex CLI | appends `[mcp_servers.netconverter]` to `~/.codex/config.toml` | Restart Codex |
| `vscode` | VS Code | this folder's `.vscode/mcp.json` | MCP: List Servers → start `netconverter` |
| `windsurf` | Windsurf | `~/.codeium/windsurf/mcp_config.json` | Cascade → MCP → refresh, or restart |
| `lmstudio` | LM Studio | `~/.lmstudio/mcp.json` | Restart; use a tool-capable model |

Every JSON file keeps a `.bak` and every other key is preserved. `--print` shows the
change without writing; `--yes` applies without asking.

The Gemini **web/mobile app** and other chat apps that cannot start a local program are
not supported by the bridge; use one of the assistants above, or a
[remote-connector](README.md) assistant for read-only access.
