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
proxied. `netconverter mcp --strict` (or `NETCONVERTER_MCP_STRICT=1`) narrows the
remote tools to the strict-view set (job list and selection, account, search and
fetch, knowledge base, vendor capabilities, job brief, evidence, report), whatever
the server advertises, and asks the server for its strict view on every request
(`X-NetConverter-View: strict`; a session can only lower the grant's view). Under
the server's strict view mode, names in results arrive as `<name:…>` tokens. While
the server is not applying it, the bridge refuses the configuration-content calls
(`unparsed_lines`, `focus=target`, non-`kb:` fetch) and masks every address in
remote results as `<ip>`/`<cidr>` itself; names in summaries are not tokenised
locally, and `account.strict_enforced_by` says which side is enforcing. `account`
returns only tier, job types, rate limit, daily quota, auth kind, credential source,
view mode and client version facts: no tokens, e-mail addresses, key hints or
tenant IDs. `wait_for_job` progress messages carry only an allowlisted
status, stage and percentage.

### Keep the assistant out of the files

The bridge uploads a configuration by **path**: it reads the file itself and sends
it to NetConverter, so the assistant never needs the file's text. An assistant
with its own file tools could still open the file and place its contents in the
model conversation. For Claude Code, `netconverter connect claude-code` therefore
offers (default yes) a deny rule `Read(//<folder>/**)` in the user-scope
`~/.claude/settings.json` (`//` is Claude Code's absolute-path form), merged with
your existing `permissions.deny` entries after a `.bak` copy. It also keeps
Claude Code from reading the reports the bridge downloads into that folder; open
those yourself. The rule governs Claude Code's file-read tools. It does not stop
a shell command you approve. Other assistants, including Claude Desktop with a
file-access extension, need their own settings; review what you allow.

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
