# claude.ai, Claude Desktop chat and the Claude mobile app

Add NetConverter once as a **custom connector** on claude.ai. It then appears under
Connectors everywhere you use Claude with that account: claude.ai on the web, the
Claude mobile apps, Claude Desktop chat, and the Claude Code tab of Claude Desktop.

The remote connector reads your jobs, results, account and the NetConverter knowledge
base. To **submit** configurations, also set up the [terminal bridge](claude-desktop.md).

## Add the connector (about a minute)

1. Open **claude.ai → Settings → Connectors → Add custom connector**.
2. Fill it in:
   - **Name:** `NetConverter`
   - **Remote MCP server URL:** `https://api.netconverter.ai/mcp/v1`
   - **Advanced settings → OAuth Client ID:** `RjSv1z2Gms6iS96s`
   - Leave **OAuth Client Secret** empty. It is a public client, so sign-in is secured
     with PKCE instead of a secret.
3. Click **Add**, then **Connect**, and sign in with your NetConverter account.
   Your administrator must have MCP access enabled for you, or the sign-in ends with
   "not enabled for this account".

On Team and Enterprise plans an organization owner may need to add the connector for
the organization first (**Admin settings → Connectors**); members then click Connect.

## Use it

- In a chat, open the **+** menu → **Connectors** and make sure NetConverter is on.
- Try: *"List my recent NetConverter jobs"*, *"How did job tra_… go?"*,
  *"How does Check Point NAT map to Palo Alto?"*
- In the Claude Desktop **Code** tab, turn the connector on for the session from the
  session's connector list.

## Remove it

claude.ai → Settings → Connectors → NetConverter → **Disconnect** or **Remove**.
