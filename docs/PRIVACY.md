# Privacy and data flow

## Two separate connections

```text
Selected config + explicit parameters ── HTTPS ──> NetConverter service
                                  <── job status, reports, verified artifacts

Allowlisted operation intent ──> Optional selected model provider
                             <── One permitted operation

Your AI assistant ── file path ──> netconverter mcp (on this machine) ── HTTPS ──> NetConverter
                  <── job id, sha256, byte count, summaries ──
```

With the full API, choosing a file only pins it by SHA-256; the file is sent when
you choose **Submit** (a pilot key uploads at selection, after its own confirmation).

Selecting a file uploads its full contents directly to NetConverter. This is a
hosted conversion service, not an offline engine. Raw configurations, generated
configurations, reports, object identifiers, and addresses are excluded from the
client's automatic model requests. Unknown words in natural-language input become
fixed opaque references before a provider call; full prompts are not saved as a
conversation transcript. Detailed results are rendered locally and saved to your
workspace, not supplied as model context.

The same restricted operation schema applies to Anthropic, OpenAI, Gemini, and
Ollama. Hosted adapters use fixed official endpoints. Ollama uses a loopback
endpoint, and failure does not trigger a hosted fallback. A loopback connection
alone does not prove that an independently configured model runtime is offline;
choose a local model and review that runtime's network settings separately.
The terminal neither bundles nor downloads model weights.

## What your AI assistant can call

The bridge offers its local tools (`submit_file`, `job_status`, `wait_for_job`,
`account`, `download`) and proxies NetConverter's remote tools only from a fixed
client-side allowlist of read tools. A tool the server adds later is not offered
until a client release lists it, and a remote tool named `submit_*` is never
proxied.

### Exposure levels

You choose how much of a job's results an assistant sees, per workspace folder
(`netconverter privacy level`, default **masked**):

- **none**: verdicts, statuses, counts and ids only. The bridge removes every other value from
  every result and withholds non-JSON text.
- **masked**: the server's strict view (names arrive as `<name:…>` tokens) and the strict tool set
  (job list and selection, account, search and fetch, knowledge base, vendor capabilities, job
  brief, evidence, report). The bridge also refuses the configuration-content calls
  (`unparsed_lines`, `focus=target`, non-`kb:` fetch) and masks every address as `<ip>`/`<cidr>`.
  Names are tokenised only by the server's strict view, not locally; `account.strict_enforced_by`
  says whether the server or only the bridge is enforcing it.
- **selected**: masked, plus the sections you chose (`--sections nat,routes`, …), which add their
  summary tools or lift one of those refusals. Results stay masked; the server serves this level as
  its strict view until per-section un-tokenising ships.
- **full**: the results as the server serves them for your account (0.4.x `--full`).

At **every** level the bridge strips secrets client-side: values of keys such as `psk`,
`password`, `community`, `*_hash`, configuration syntax such as `pre-shared-key X`,
`snmp-server community X`, `password 7 X`, `secret 5 X`, and crypt/`ENC`/`-AQ==` hashes become
`<secret>`. This is defence in depth over the server's own view; it is pattern-based and does not
replace the server's handling.

The bridge sends the level as `X-NetConverter-View` on every remote request; the server applies
min(your grant, the level), so a session can only lower what the tenant's grant allows, and
`account` reports `exposure_level`, the server's `view_mode` and, when sent, `view_mode_grant`
and `view_clamped`. The level is re-read on every call, so lowering it takes effect at once.

**Raising the level requires typing `raise to LEVEL` in a terminal.** `netconverter privacy level`
refuses a raise when stdin or stdout is not a terminal, so no script, pipe, MCP tool or model can
raise it; lowering works anywhere. Every change is appended to
`.netconverter/privacy-audit.jsonl` (time, old → new, sections, OS user, folder, `tty` or
`not_needed`). A `privacy.json` above masked without a matching typed raise in that log is ignored
(the bridge uses masked and says so). The `.netconverter` folder is never a source or destination
for any bridge tool, so neither file is reachable through MCP.

**Flags and precedence.** The folder's level is the ceiling. `netconverter mcp --level LEVEL`,
`--strict` (= masked), `--full` (= full) or `NETCONVERTER_MCP_VIEW` can only lower it for one bridge
process (a flag beats the variable); `--full` therefore widens the view only after
`netconverter privacy level full`. `--guided` serves at most masked and refuses `none`.
`netconverter connect` writes no view flag (0.4.4 wrote `--strict`; reconnect to drop it).
**Upgrade note (0.5.0):** an assistant that relied on `--full` now gets masked until you raise the
folder's level in a terminal.

The `account` tool
returns only tier, job types, rate limit, daily quota, auth kind, credential source,
exposure level, view mode and client version facts: no tokens, e-mail addresses, key hints or
tenant IDs. `job_status` and `wait_for_job` (and its progress messages) carry an
allowlisted status and percentage plus the stage: the server's fixed-vocabulary
`stage_key` when it sends one, otherwise its progress text made single-line,
stripped of control characters and capped at 120 characters; a stage that names an
internal id (for example "Stored to corpus (ID: …)") is reported as `storing`.

`submit_file` accepts job `options` only from a fixed, typed allowlist (its schema
lists every key). The file, vendors, job type, `technology`, and any decisions document
(`yaml_v2`, `yaml`, `manual_mappings`) can never come from options, and an unknown key
is refused naming it before anything is uploaded.

### Keep the assistant out of the files

The bridge uploads a configuration by **path**: it reads the file itself and sends
it to NetConverter, so the assistant never needs the file's text. An assistant
with its own file tools could still open the file and place its contents in the
model conversation (tester MCP-C4: every client except Claude Desktop can, when the
folder is in reach). `netconverter privacy apply --client CLIENT` sets the client's own
deny rules for the folder; it shows a diff, applies only after yes, keeps a `.bak`, and a
second run changes nothing:

- **Claude Code**: `Read(//<folder>/**)` and `Edit(//<folder>/**)` in the user-scope
  `~/.claude/settings.json` `permissions.deny` (`//` is Claude Code's absolute-path form).
  `netconverter connect claude-code` also offers the Read rule (default yes). Its Bash tool is not
  covered: keep it on ask, or add `Bash(cat:*)` yourself (that blocks `cat` everywhere).
- **Cursor CLI**: `Read(<folder>/**)` and `Write(<folder>/**)` in `~/.cursor/cli-config.json`
  `permissions.deny`; add the folder to the opened project's `.cursorignore` if it sits inside it.
- **Gemini CLI**: `~/.gemini/policies/netconverter-<id>.toml` denies `read_file`,
  `read_many_files`, `write_file`, `replace`, `glob`, `list_directory`, the search tools and
  `run_shell_command` any argument naming the folder; add it to `.geminiignore` too.
- **Codex** (printed, not applied): a permission profile with `"<folder>" = "deny"` made active
  by `default_permissions`; it replaces your active sandbox profile, so you add it.
- **OpenClaw** (printed, not applied): an agent workspace other than the folder,
  `tools.deny: ["read", "exec"]`, `tools.fs.workspaceOnly: true`, `sandbox.workspaceAccess: "none"`.

Deny rules also keep the client from reading the reports the bridge downloads into that folder;
open those yourself. Start each client outside the folder: one started in it or a parent folder
reaches the files through its project tools. These settings govern the client's own tools; they
do not stop a shell command you approve, and the tests prove the files written, not each live
client's enforcement.

## Tools and files

Models request one allowlisted operation. They receive no shell, unrestricted
filesystem, arbitrary URL, or arbitrary server endpoint tool. Sensitive values
such as addresses and object names are entered through structured commands and
sent directly to NetConverter. Configuration comments and report text are data;
they are never executed as instructions.

The workspace boundary rejects paths and symlinks that escape the chosen folder.
Output names include the server job ID. Downloads verify the manifest, length,
and SHA-256 before atomic writes. Identical existing files can be reused;
differing files are preserved and produce an error. Hash verification detects
mismatches; it does not replace trust in the server producing the artifacts.

## Credentials and local state

The supported OS credential store holds API keys when available; the client
refuses plaintext keyring backends. Otherwise keys are entered for the session
and held in memory. On macOS, the Keychain service is `NetConverter Terminal` (kept under that name
since 0.1.x so saved credentials survive the rename to NetConverter CLI).
Server accounts are scoped to the server URL; model accounts are provider names.
Credentials are never written into `.netconverter/`.

The workspace contains non-secret connection preferences, filenames, revision
hashes, job handles, and retry metadata. Some structured conversion decisions can
also appear in pending-request metadata. These records and downloaded findings
may still be sensitive. Keep the folder private and out of public repositories.
The client does not persist a free-text prompt transcript or provider responses.
The local MCP bridge appends one metadata line per tool call to
`.netconverter/bridge.jsonl` (time, assistant name, tool, relative path, SHA-256,
byte count, job id, vendors, status) so the app can show `/activity`. It never
records configuration text, tool results or credentials, and keeps the newest 500 lines.

`netconverter update` and the daily update check contact only the public GitHub
API for `valeronlabs/netconverter_terminals` (and GitHub's release download hosts),
with no NetConverter credential. The request carries a `netconverter-cli/<version>`
User-Agent. The check stores the latest version and check times in
`update-check.json` in your user cache folder (`~/Library/Caches/netconverter` on
macOS), never in the workspace. `NETCONVERTER_NO_UPDATE_CHECK=1` turns the daily
check off; `netconverter mcp` never prints the notice. Its `account` tool reads
the same cache and, when the cache is more than a day old, makes the same check
with a 3-second timeout. An update installs only a wheel whose SHA-256
matches the release's `SHA256SUMS`. Both files come from the same release, so
this detects a corrupted or swapped download, not a compromised release.

Production uses HTTPS with certificate verification. The client rejects plain
HTTP except explicit loopback addresses for development, ignores environment
proxy settings, and does not follow redirects. Local downloaded artifacts are
**ordinary files**; there is no password-encrypted output bundle in this release.
Use your OS storage protection and organization policy for files at rest.

## Verification boundary

Automated client tests exercise synthetic canaries, provider payload abstraction,
forbidden operations, workspace escape attempts, output preservation, and
interrupted sessions. Every request is tenant-scoped by the credential. A 0.1.x
Terminal Quick key reaches only its restricted pilot profile; full-API keys and
Clerk sign-ins reach the External API (`/jobs`, `/capabilities`) and, for questions,
the read-only NetConverter MCP tools. Full-fidelity server AI stays opt-in per tenant.

**The complete audit of backend AI-provider payloads remains open.** Client tests
and clean diagnostic-log checks do not establish that every downstream server
provider path has been audited. Use synthetic configurations for initial public
pilot testing and obtain the relevant backend privacy acceptance before uploading
sensitive customer configurations. See [verification status](VERIFICATION.md).

No client can prevent a user from separately pasting a configuration into another
AI application. This document describes this client's implemented boundary.
