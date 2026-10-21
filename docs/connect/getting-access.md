# Getting NetConverter MCP access

For a new user (a colleague, partner or evaluator) who wants NetConverter in their AI assistant.
Two parts: the **NetConverter administrator** enables the account, then the **user** connects
an assistant. About ten minutes in total.

## Part 1 — administrator

1. **Put the user in a regular organization.** MCP is not available on the Quick tier or in a
   shared tenant. Invite the user's email to an existing organization, or create a dedicated
   one (for example "Evaluation") with a few sample jobs so there is something to look at.
2. **The user signs in once** at <https://netconverter.ai> with that email (sign-up or the
   invitation link), so their account is linked to the organization.
3. **Grant MCP access:** Admin portal → **MCP Management** → **Add grant** → pick the
   organization and the user → view mode **Default** (or **Strict** if configuration names
   must not reach their AI) → optional daily caps → **Save**. Access starts within 30 seconds.
4. Send the user this page and tell them which organization to use.

To revoke later: MCP Management → the grant → disable or delete.

## Part 2 — user

### Option A: no install (claude.ai, Claude Desktop chat, Claude mobile)

Read-only: jobs, verdicts, evidence, reports, account and the migration knowledge base.

1. Open **claude.ai → Settings → Connectors → Add custom connector**.
2. Name `NetConverter`, URL `https://api.netconverter.ai/mcp/v1`.
   **Advanced settings → OAuth Client ID:** `RjSv1z2Gms6iS96s` (leave the secret empty).
3. **Add**, then **Connect**, and sign in with your NetConverter account.
4. In a chat: **+ → Connectors →** turn on NetConverter. Ask: *"Show my NetConverter account"*,
   then *"List my recent NetConverter jobs"*.

ChatGPT works the same way: see [chatgpt.md](chatgpt.md).

### Option B: terminal client (Claude Desktop, Claude Code, Cursor, Gemini CLI, Codex …)

Everything in Option A **plus submitting configurations**; files are uploaded from your
computer and never pass through the AI model.

1. Install [uv](https://docs.astral.sh/uv/getting-started/installation/), then the CLI from the
   [latest release](https://github.com/valeronlabs/netconverter_terminals/releases/latest):
   ```sh
   uv tool install --python 3.12 --force git+https://github.com/valeronlabs/netconverter_terminals
   ```
2. Sign in and connect your assistants:
   ```sh
   netconverter login --clerk
   mkdir -p ~/migrations
   netconverter --workspace ~/migrations connect --all
   ```
   Keep the configurations you want to work on in `~/migrations`.
3. Fully quit and reopen each assistant. Ask: *"What NetConverter tools do you have?"*

`netconverter update` installs new releases.

## If something does not work

| Message or symptom | Meaning |
|---|---|
| "not enabled for this account" / `mcp_not_granted` | Part 1 step 3 is missing for this user. |
| "not available on the quick tier" / "shared tenants" | Part 1 step 1: move the user into a regular organization. |
| Sign-in loops on claude.ai | Check the OAuth Client ID in the connector's advanced settings. |
| No NetConverter tools in the assistant | Quit and reopen it; run `netconverter connect` to check. |

More detail: [connection guides](README.md) · [privacy](https://netconverter.ai/privacy) · support: contact@netconverter.ai
