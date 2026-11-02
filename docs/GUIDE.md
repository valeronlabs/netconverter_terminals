# NetConverter terminal guide — what everything means

This guide explains the ideas behind the `netconverter` commands: how you sign in, what a
workspace folder is, what an AI assistant may see (exposure levels), how assistants connect,
how a guided migration runs, and what each error means. Every command and flag is listed in
the [CLI reference](CLI_REFERENCE.md); settings and environment variables are in
[COMMANDS.md](COMMANDS.md); the data flow and threat model are in [PRIVACY.md](PRIVACY.md).

Contents:
[Sign-in and credentials](#sign-in-and-credentials) ·
[Workspace folders](#workspace-folders) ·
[Privacy and exposure levels](#privacy-and-exposure-levels) ·
[AI assistants and the MCP bridge](#ai-assistants-and-the-mcp-bridge) ·
[Job types](#job-types) ·
[Guided migration](#guided-migration-prescan-decisions-conversion) ·
[Confirmations](#confirmations-before-an-upload-or-a-conversion) ·
[Updating](#updating) ·
[Error codes](#error-codes-and-what-to-do)

## Sign-in and credentials

NetConverter accepts two kinds of credential. You need one of them; both work for the
terminal, the app and the MCP bridge.

| | `netconverter login --clerk` | `netconverter login` (API key) |
| --- | --- | --- |
| What it is | Your **NetConverter account** (OAuth through Clerk, the identity provider behind the portal). | An **API key** (`nck_…`) issued to you or your organisation in the portal (enterprise or trial keys). |
| How you sign in | A browser opens; you sign in as on netconverter.ai. `--device` prints a code to enter on another device (SSH, containers). | You paste the key at a hidden prompt; it is never echoed. |
| What it can do | Everything your account's tenant allows. | What the key's **scopes** allow: `read:jobs` (results), `write:jobs` (submit jobs, including prescans), `mcp:tools` (the remote MCP tools). |
| Typical use | People at their own computer. | Automation, shared machines, and customers who manage access with keys. |

**Where it is kept.** In the operating system's credential store (macOS Keychain, Windows
Credential Manager, Secret Service on Linux). Where none is reachable, or with
`--store file`, in a passphrase-encrypted file (AES-256-GCM): set
`NETCONVERTER_CREDENTIAL_PASSPHRASE` or `NETCONVERTER_CREDENTIAL_PASSPHRASE_FILE`. Never in
plain text.

**Which one is used.** Plain commands use a stored API key first, then your sign-in. The MCP
bridge (`netconverter mcp`) prefers the sign-in and says on stderr which key it leaves
unused. Force one with `--auth clerk|key` (bridge) or `NETCONVERTER_AUTH=clerk|key`. One
process always uses one credential for everything it does.

- `netconverter whoami` shows who is signed in and where the credential is kept; it never
  prints a token.
- `netconverter logout` removes the sign-in; `logout --all` also removes the stored API key.
- `netconverter capabilities` (or `allowance`) shows the vendors, conversion paths, job types
  and limits your credential has.
- A 0.1.x **Terminal Quick** pilot key reaches only the pilot profile (ASA → Palo Alto,
  50 KB); it has no prescan.

## Workspace folders

Everything the terminal reads or writes stays inside one **workspace folder**: the current
folder, or the one given with `--workspace DIR` (a global option, before the command). Paths
outside it, symbolic links that leave it, and the `.netconverter/` state folder are refused.
The state folder keeps the active job, the bridge activity log (paths, sizes, hashes and job
ids only) and the folder's privacy setting.

`--server URL` chooses the NetConverter API (default `https://api.netconverter.ai/external/v1`).
Use a dedicated folder per migration project, for example `~/migrations`, not your home folder.

## Privacy and exposure levels

Your configuration files never go through an AI model: the bridge reads the file and uploads
it directly to NetConverter. What an assistant **does** see are the **results**: summaries,
findings, decisions. The folder's **exposure level** decides how much of them.

| Level | What the assistant sees | Server view | Guided-migration tools |
| --- | --- | --- | --- |
| `none` | Verdicts, statuses, counts and ids only. | strict | No |
| `masked` (default) | Summaries with configuration names as `<name:…>` tokens and addresses as `<ip>`/`<cidr>`; no configuration content. | strict | No (the prescan itself still runs) |
| `selected` | `masked`, plus the sections you choose (`interfaces`, `routes`, `policy`, `nat`, `vpn`, `objects`, `management`, `translation`, `unparsed_lines`, `target`, `reports`). | strict | No |
| `full` | Results as the server serves them for your account: your own addresses and names; secrets still redacted. | default | **Yes** (write tools only where enabled for your tenant) |

- **Secrets are removed at every level** (pre-shared keys, SNMP communities, password hashes),
  by the server and again by the bridge.
- **The server view.** NetConverter's MCP server has two views: *default* (your tenant's own
  addresses and names) and *strict* (tokens and masks, no configuration-content tools). The
  bridge sends the level on every request; the server applies the lower of your grant and the
  level. The strict view lists **no** guided-migration tools and **no** write tools, so a
  guided migration needs `full`.
- **Why raising needs a typed confirmation.** `netconverter privacy level full` asks you to type
  `raise to full` in a terminal. It refuses without a terminal, so no script, AI assistant or
  MCP tool can widen what an assistant sees. Lowering needs no confirmation. Every change is
  recorded in `.netconverter/privacy-audit.jsonl`.
- **Per process.** `netconverter mcp --level LEVEL` (or `--strict`, or `NETCONVERTER_MCP_VIEW`)
  can only lower the folder's level for one bridge process; `--full` works only once the folder
  is at `full`.
- `netconverter privacy status` shows the level and recent changes; `privacy apply --client …`
  keeps an assistant's own file-reading tools out of the folder, so it works on your
  configurations only through the bridge.

After you change the level, restart (or reconnect) the assistant: assistants keep the tool list
they read when they started.

## AI assistants and the MCP bridge

An AI assistant reaches NetConverter in one of two ways:

| | Terminal bridge (`netconverter mcp`) | Hosted connector (`https://api.netconverter.ai/mcp/v1`) |
| --- | --- | --- |
| Runs | On your computer, started by the assistant. | At NetConverter; the assistant connects over HTTPS with OAuth. |
| Can upload files | **Yes**, by path, from the workspace folder. | No. |
| Assistants | Claude Code, Claude Desktop, Cursor, VS Code, Codex CLI, the **ChatGPT desktop app's agent**, Gemini CLI, Windsurf / Devin, LM Studio, OpenClaw. | claude.ai, ChatGPT (web and apps), Claude Desktop chat. |
| Set up with | `netconverter connect <assistant>` in the folder. | `netconverter connect chatgpt` / `claude-ai` print the steps (client ID `RjSv1z2Gms6iS96s`, no secret). |

`netconverter connect` shows the exact change it makes and asks first; JSON settings files
keep a `.bak`. If the assistant already has a `netconverter` entry, `connect` shows it instead
of changing it: edit its `--workspace` argument yourself.

**ChatGPT.** The ChatGPT desktop app's agent runs MCP servers from `~/.codex/config.toml`, the
same file Codex CLI uses, so `netconverter connect codex` in your folder connects it; restart
ChatGPT afterwards. Step by step: [connect/chatgpt.md](connect/chatgpt.md).

**Bridge tools.** Local: `submit_file`, `job_status`, `wait_for_job`, `account`, `download`.
Proxied from NetConverter (only from a fixed list in the client, and only what the server
offers to your account at your level): reports, evidence, NAT, routes, flows, objects, the
knowledge base, guided mapping (`get_mapping_questions`, `validate_mapping`,
`apply_mapping_answers`), guided migration (`list_operations`, `get_decision_document`,
`validate_decision_document`, `propose_operations`, `submit_conversion`) and
`set_view_level`. The full list is in [COMMANDS.md](COMMANDS.md#mcp-bridge-tools). `account`
says which guided tools this session has and, when they are hidden, why.

**Write tools.** `propose_operations`, `submit_conversion` and `apply_mapping_answers` create
work. The server lists them only in the default view (level `full`) and only for tenants
where a NetConverter administrator enabled them; it checks and audits every call.

## Job types

| Job type | Command / tool | What it does |
| --- | --- | --- |
| `validate` (`analyze`) | `netconverter validate FILE --vendor V` / `submit_file job_type=validate` | Readiness, findings and parse gaps for one configuration. |
| `optimize` | `netconverter optimize FILE --vendor V` | Cleanup and optimization findings (unused objects, shadowed rules, …). |
| `convert` | `netconverter convert FILE --vendor V --to T` | Translates the configuration to the target vendor in one step. |
| `prescan` | `submit_file job_type=prescan` (bridge) | Reads the configuration and stops with a **decision document**: nothing is converted until you decide. Starts a guided migration. |

Vendor codes (`cisco_asa`, `palo_alto_xml`, `fortinet`, …) and the supported paths come from
`netconverter capabilities`.

## Guided migration (prescan, decisions, conversion)

A guided migration lets you decide how each item is handled before anything is converted.
Ask your assistant, for example: *"Prescan ~/migrations/edge.cfg from ASA to Palo Alto XML and
walk me through the decisions."*

1. **Prescan.** `submit_file(path, source_vendor, target_vendor?, job_type="prescan")` uploads the
   file; the job gets a `psc_` id and stops. `wait_for_job` until it is completed.
2. **Read the decisions.** `list_operations` (what can be decided), `get_decision_document` (the
   current revision and its `sha256`) and `validate_decision_document`, each with
   `job_id=psc_…`.
3. **Decide.** The assistant asks you about each item; it must not choose *skip* for you.
   `propose_operations(job_id, changes, base_sha256)` records your choices as a new revision.
4. **Convert.** With your OK, `submit_conversion(job_id, revision)` queues the conversion as a new
   `tra_` job (the assistant confirms with you first, see below).
5. **Results.** `wait_for_job`, then `get_job_brief` / `get_evidence`, and `download` saves the
   translated configuration, the report and the evidence workbook in the folder, hash-verified.

Needs: a credential that can submit jobs (sign-in, or an API key with `write:jobs`), the folder at
exposure level `full`, and the write tools enabled for your tenant. Without the write tools you
can still prescan and read the decisions, then convert in Quick Convert or Conversion Studio.

## Confirmations before an upload or a conversion

Before `submit_file` uploads a file, and before `submit_conversion` or `apply_mapping_answers`
queue a conversion, the bridge asks **you**:

- **Assistants that show forms** (MCP elicitation): a dialog with the path, size and SHA-256 (or
  the job and revision). Accept sends it; Decline or closing the dialog sends nothing
  (`upload_declined` / `apply_declined`).
- **Assistants that cannot show the form** (ChatGPT, Claude Code and others answer it
  automatically, unseen): the bridge sends nothing and answers `confirmation_required` with a
  single-use `confirm_token` for that exact call (valid 10 minutes). The assistant must ask you
  in the conversation; only after your yes does it repeat the call with the token.
- **No forms at all:** `netconverter mcp --no-upload-confirm` (or
  `NETCONVERTER_MCP_UPLOAD_CONFIRM=0`) relies on the assistant's own tool-approval prompt only.

## Updating

`netconverter update --check` says whether a newer release exists; `netconverter update`
installs it (with `uv`, from PyPI, or the verified GitHub release). Then restart your AI
assistants so they start the new bridge and read its tool list again.

## Error codes and what to do

Bridge and server errors come back to the assistant as a JSON object with `error` (the code)
and `message`.

| Code | Meaning | What to do |
| --- | --- | --- |
| `not_signed_in` | No credential reachable. | `netconverter login --clerk` (or `login` with a key); the bridge picks it up on the next call. |
| `keyring_unreachable` | The assistant started the bridge without access to the OS keyring (Linux). | Set `DBUS_SESSION_BUS_ADDRESS` (or `NETCONVERTER_API_KEY`) in the assistant's MCP settings; restart it. |
| `unauthorized` | NetConverter refused the credential. | `netconverter whoami`; sign in again or check the key. |
| Any code with `http_status: 403` | The credential lacks a permission (for example `write:jobs`); the message names what is missing. | `netconverter capabilities`; ask your administrator for the scope. |
| `not_available` | That job type is not available for this credential (for example `prescan` with a pilot key). | Use a sign-in or a full API key; `account` lists `job_types`. |
| `invalid_path` | The path is outside the workspace folder, a link, or not a file. | Put the file in the folder the bridge was started with. |
| `invalid_arguments` | A missing vendor, an unknown option, or an option that does not apply to the job type. | The message names the field. |
| `confirmation_required` | The assistant could not show the confirmation form. | Answer the assistant's question in the chat; it retries with the token. Or `--no-upload-confirm`. |
| `upload_declined` / `apply_declined` | You declined or closed the confirmation (`reason` says which). | Nothing was sent. Ask again if you meant yes. |
| `invalid_confirm_token` | The token was used, expired, or belongs to a different call. | The assistant calls again without a token and asks you again. |
| `strict_mode` | The level hides configuration content (for example unparsed lines or target config). | `netconverter privacy level selected --sections …` or `full`. |
| `level_none` | Guided mapping needs more than level `none`. | `netconverter privacy level masked` (or higher). |
| `unknown_tool` | The tool is not offered at this level or to this account. | `account` → `guided_migration` names the fix; restart the assistant after changing the level. |
| `write_tools_disabled` (server) | `propose_operations` / `submit_conversion` / `apply_mapping_answers` are not enabled for your tenant. | Ask a NetConverter administrator to enable the write tools for your tenant, or decide and convert in Conversion Studio / Quick Convert. |
| `oauth_client_not_enrolled` (server) | The app signing in to the hosted connector is not an accepted NetConverter client (self-registered apps are refused). | Use the terminal bridge (`login --clerk` + `connect`), or enter client ID `RjSv1z2Gms6iS96s` with no secret, or an API key with `mcp:tools`. |
| `audit_unavailable` (server) | The audit record for a write could not be written, so nothing happened. | Retry shortly. |
| Any code with `http_status: 429` | Too many requests, the daily quota, or too many jobs in flight. | Wait; `account` shows the limits. |

More symptoms (installation, keyring, file size, proxies) are in
[COMMANDS.md § Troubleshooting](COMMANDS.md#troubleshooting).
