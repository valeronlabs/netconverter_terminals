# Privacy and data flow

## Two separate connections

```text
Selected config + explicit parameters ── HTTPS ──> NetConverter service
                                  <── job status, reports, verified artifacts

Allowlisted operation intent ──> Optional selected model provider
                             <── One permitted operation
```

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
and held in memory. On macOS, the Keychain service is `NetConverter Terminal`.
Server accounts are scoped to the server URL; model accounts are provider names.
Credentials are never written into `.netconverter/`.

The workspace contains non-secret connection preferences, filenames, revision
hashes, job handles, and retry metadata. Some structured conversion decisions can
also appear in pending-request metadata. These records and downloaded findings
may still be sensitive. Keep the folder private and out of public repositories.
The client does not persist a free-text prompt transcript or provider responses.

Production uses HTTPS with certificate verification. The client rejects plain
HTTP except explicit loopback addresses for development, ignores environment
proxy settings, and does not follow redirects. Local downloaded artifacts are
**ordinary files**; there is no password-encrypted output bundle in this release.
Use your OS storage protection and organization policy for files at rest.

## Verification boundary

Automated client tests exercise synthetic canaries, provider payload abstraction,
forbidden operations, workspace escape attempts, output preservation, and
interrupted sessions. Server access uses a restricted tenant-scoped terminal
profile; its key cannot access the ordinary API catalog. Pilot enrollment keeps
full-fidelity server AI opt-in disabled.

**The complete audit of backend AI-provider payloads remains open.** Client tests
and clean diagnostic-log checks do not establish that every downstream server
provider path has been audited. Use synthetic configurations for initial public
pilot testing and obtain the relevant backend privacy acceptance before uploading
sensitive customer configurations. See [verification status](VERIFICATION.md).

No client can prevent a user from separately pasting a configuration into another
AI application. This document describes this terminal's implemented boundary.
