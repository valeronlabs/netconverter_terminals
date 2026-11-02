# ChatGPT

ChatGPT reaches NetConverter in two ways:

- **ChatGPT desktop app's agent (Codex)**, on your computer: it runs this terminal's bridge, so
  it can **upload configuration files** by path and run a **guided migration** (prescan →
  decisions → conversion). Setup below under *Upload files from ChatGPT*.
- **The hosted connector** (chatgpt.com, any ChatGPT app): reads your jobs, results, account
  and the knowledge base; it cannot submit configurations. Setup under *Add the connector*.

`netconverter connect chatgpt` prints both.

## Upload files from ChatGPT (desktop app agent)

The ChatGPT desktop app's agent reads its MCP servers from `~/.codex/config.toml`, the same
file Codex CLI uses. Use a dedicated folder for your configurations (not your home folder):

```sh
netconverter login --clerk                          # once; or an enterprise API key with write:jobs
mkdir -p ~/migrations && cd ~/migrations
netconverter connect codex                          # adds [mcp_servers.netconverter] for this folder
netconverter privacy level full                     # needed for the guided-migration tools; type the phrase
```

Then restart ChatGPT. If `~/.codex/config.toml` already has `[mcp_servers.netconverter]`,
`connect` shows the table instead of changing it: edit its `args` to
`["mcp", "--workspace", "/Users/<you>/migrations"]`.

What happens in a chat (*"Prescan ~/migrations/edge.cfg from ASA to Palo Alto XML and walk me
through the decisions"*):

1. ChatGPT asks to run `submit_file`: approve it in ChatGPT's own tool prompt.
2. ChatGPT cannot show the bridge's upload form (it declines it unseen), so the bridge sends
   nothing and answers `confirmation_required`. ChatGPT asks you in the chat whether to upload
   that file (path and size); only when you say yes does it repeat the call with the
   single-use `confirm_token`. The file goes from disk to NetConverter; its text never passes
   through ChatGPT. The job stops at a `psc_` prescan.
3. ChatGPT reads the decisions (`list_operations`, `get_decision_document`,
   `validate_decision_document`), asks you about each one, records your choices with
   `propose_operations`, and with your OK queues the conversion with `submit_conversion`
   (asked in the chat the same way). `download` saves the Palo Alto output in the folder.

Exposure level: the guided-migration tools need `full` for the folder. At `masked` (the default)
the prescan still runs, and `account` says the tools are hidden and how to fix it. The write tools
(`propose_operations`, `submit_conversion`) are listed only where they are enabled for your
tenant. If you prefer ChatGPT's own tool approval as the only confirmation, add
`"--no-upload-confirm"` to the `args` (or set `NETCONVERTER_MCP_UPLOAD_CONFIRM=0`).
ChatGPT keeps the tool list from when it started: restart it after an update or a level change.

## Add the connector

1. In ChatGPT: **Settings → Apps & Connectors → Advanced settings** → turn on
   **Developer mode**, then **Create** a custom connector.
2. Fill it in:
   - **Name:** `NetConverter`
   - **MCP server URL:** `https://api.netconverter.ai/mcp/v1`
   - **Authentication:** OAuth. Under the advanced OAuth settings enter
     **Client ID** `RjSv1z2Gms6iS96s` and leave the client secret empty.
3. Save, then sign in with your NetConverter account when asked.
4. In a chat, enable NetConverter from the **+** menu (Developer mode).

Developer mode and custom connectors depend on your ChatGPT plan and workspace
settings; on business workspaces an admin may need to allow them.
