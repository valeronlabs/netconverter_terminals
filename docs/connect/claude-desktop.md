# Claude Desktop (terminal bridge)

The terminal bridge lets Claude Desktop chat **submit** configurations as well as read
results. Claude passes a file path; the bridge uploads the file directly, so the
configuration text never goes through the model.

## Set up

Install (skip if `netconverter --version` works):

```sh
curl -LsSf https://netconverter.ai/install.sh | sh -s -- --no-connect   # macOS / Linux
```
```powershell
$env:NETCONVERTER_INSTALL_NO_CONNECT=1; irm https://netconverter.ai/install.ps1 | iex   # Windows
```

Manual: `uv tool install --python 3.12 netconverter-cli` — see [getting access](getting-access.md).

Then:

```sh
netconverter login --clerk
netconverter --workspace ~/migrations connect claude-desktop
```

`connect` shows the change to `claude_desktop_config.json` (macOS:
`~/Library/Application Support/Claude/`, Windows: `%APPDATA%\Claude\`), asks, keeps a
`.bak`, and leaves every other server untouched. `--workspace` is the folder whose
files Claude may hand to the bridge; keep your configurations there.

Then **quit Claude Desktop completely** (Cmd+Q / File → Exit) and reopen it. Claude
Desktop reads MCP servers only at startup.

## Check

Ask Claude: *"What NetConverter tools do you have?"* You should see `submit_file`,
`job_status`, `wait_for_job`, `download` and `account` plus the NetConverter read tools.
Then: *"Validate ~/migrations/edge-fw.conf as Fortinet"*.

To also use NetConverter on claude.ai and mobile, add the
[remote connector](claude-ai.md) too; both can be on at once.
