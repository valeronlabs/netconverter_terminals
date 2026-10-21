# ChatGPT

ChatGPT can only use remote MCP servers, so it connects to NetConverter's hosted MCP.
It reads your jobs, results, account and the knowledge base; it cannot submit
configurations (use a terminal-bridge assistant for that).

`netconverter connect chatgpt` prints these same steps.

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
