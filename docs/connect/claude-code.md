# Claude Code (terminal bridge)

```sh
netconverter login --clerk
cd ~/migrations
netconverter connect claude-code
```

This runs `claude mcp add --scope user netconverter -- netconverter mcp --workspace <folder>`
for you, after showing it. It then offers a second change (Enter accepts): a
`Read(//<folder>/**)` deny rule in `~/.claude/settings.json`, so Claude Code hands
configurations to the bridge by path instead of reading their text itself.

Restart Claude Code, or run `/mcp`, to load the tools. In the Claude Desktop **Code**
tab the bridge appears in the session's MCP server list as `netconverter`.

The [remote connector](claude-ai.md) also shows up in Claude Code once it is added on
claude.ai; keep the bridge for submitting files.
