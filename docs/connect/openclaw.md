# OpenClaw

`netconverter connect openclaw` adds the terminal bridge to OpenClaw through OpenClaw's own
CLI; it never edits `~/.openclaw/openclaw.json` (JSON5) by hand.

```sh
cd ~/migrations                       # the folder with your configurations
netconverter connect openclaw         # shows the commands, asks, then runs them
netconverter connect openclaw --print # show only
netconverter connect openclaw --remove
```

What it runs after you answer yes:

```sh
openclaw mcp add netconverter --command /path/to/netconverter \
  --arg mcp --arg --workspace --arg ~/migrations
openclaw mcp doctor netconverter --probe
```

- **No view flag:** the folder's exposure level decides what OpenClaw sees (default masked;
  `netconverter privacy level`). `netconverter privacy apply --client openclaw` prints the tool
  policy that keeps OpenClaw's own `read`/`exec` tools out of the folder.
- **Idempotent.** Re-running with the same folder changes nothing. A `netconverter` entry
  pointing elsewhere is replaced (`openclaw mcp unset netconverter`, then `add`) after you
  confirm. `--remove` runs `openclaw mcp unset netconverter`.
- **No `openclaw` on PATH:** `connect` prints the JSON5 block to merge into
  `~/.openclaw/openclaw.json` under `mcp.servers`, then run
  `openclaw mcp doctor netconverter --probe`.

## Gateway host

OpenClaw starts stdio MCP servers from the **Gateway** process. `netconverter` must be
installed, on the Gateway's PATH, and signed in (`netconverter login --clerk`) on the
Gateway host, with its environment. On Linux the Gateway may start the bridge without
`DBUS_SESSION_BUS_ADDRESS`; if the bridge reports `keyring_unreachable`, add that variable
(or `NETCONVERTER_API_KEY`) to the server's `env` in OpenClaw.

## Deny OpenClaw's own file tools

OpenClaw agents have their own file and exec tools, so they could open a configuration and
put its text into the model conversation. After connecting, deny the workspace folder
(`<folder>/**`) to those tools in OpenClaw's tool policy and restart the Gateway; the
assistant then works on configurations only through the bridge, by path. `connect` shows
this step with the exact path but does not apply it.

## Compatibility

The client-compatibility matrix (Claude Code, Claude Desktop, Cursor, Gemini CLI, Codex,
OpenClaw) is filled from the tester's run on a real machine; it is not claimed here from
unit tests, which only mock `openclaw`.
