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
