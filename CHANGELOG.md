# Changelog

## 0.4.4 — 2026-10-29

**License change.** From 0.4.4 the client is licensed by ValeronLabs LLC for use with
your NetConverter account only; it may not be redistributed or modified (see LICENSE).
Versions up to 0.4.3 were MIT licensed. On first run the client shows the license and
asks you to type `accept`; scripts and containers use `netconverter license accept --yes`
or `NETCONVERTER_ACCEPT_LICENSE=1`. Until it is accepted, `netconverter mcp` answers every
tool call with how to accept it.

**Upgrade note.** `netconverter mcp` now serves the strict view by default; add `--full`
(or set `NETCONVERTER_MCP_VIEW=full`) if you relied on the wider view. `connect` writes
`--strict` for every assistant. Errors now go to stderr with distinct exit codes.

- New: `netconverter walkthrough` and `/walkthrough`, a short guided tour of jobs, privacy
  and AI integrations.
- New: `netconverter license` (`show`, `accept`, `status`).
- `connect` leaves one NetConverter server per assistant: it removes older bridge entries
  and direct `api.netconverter.ai` entries (which NetConverter now refuses) from Cursor,
  Claude Desktop, Gemini CLI, Windsurf and LM Studio, keeping every other server.
- New: `netconverter connect openclaw` (with `--remove`).
- convert / validate / optimize / resume print a short plain summary (verdict ready /
  needs review / blocked, counts, first findings, next command); `--json` gives the raw
  response and `--all` lists every finding. The app's job card shows a scorecard.
- `netconverter query unparsed_lines` (app: `/unparsed_lines`) lists unparsed lines.
- Job options are checked against a typed allowlist before upload; unknown keys and
  request fields are refused by name. Guided conversion settings reach the full API as a
  YAML v2 document instead of being silently ignored.
- `job_status` and `wait_for_job` report the job stage.
- Ctrl-C prints "Cancelled. Nothing was saved." and exits 130. Errors give the specific
  reason (file, `--options`, the server's reason); exit codes 2 usage, 3 sign-in, 4 input,
  5 server (docs/COMMANDS.md). A 403 says what your credential is missing.
- A locked system keyring is reported after 5 s instead of hanging
  (`NETCONVERTER_KEYRING_TIMEOUT_S`); one signed-out message everywhere.
- Help text for every command and option, "Did you mean …?" for typos, valid vendor
  codes when `--vendor` is missing, `--to` only on `convert`.
- App: `/refresh` (`/allowance` still works), the /help footer, `/ls` titles use `~/`.
- `update --check` prints a plain line (`--json` for JSON); one-shot JSON keeps "→".
- Auto-detect: Cisco switches no longer read as ArubaOS; IOS-XE switch vs router from the
  content; NX-OS and SRX reported as unsupported.
- Bridge: clearer options-size refusal, `account` reports a signed-out status, and
  signing in works without restarting the bridge.

- **Candidate multi-device project adapters (development preview).** New `project`
  commands and capability-gated guided MCP tools use generated server schemas,
  explicit frozen device revisions and complete link proposals. Bounded evidence
  preserves missing decisions and staleness, verifies snapshot/evidence hashes,
  and never grants project approval or execution. Server opt-in and deployment,
  target/runtime qualification and real desktop acceptance remain required.

- **Typed migration proposals (development preview).** A generated server catalog
  describes interface/zone mappings, source scope and explicit policy options.
  CLI and guided MCP validate complete batches and require a matching server
  catalog before submission. Bounded, paginated interface context separates observed
  source fields from desired mappings and reports incomplete decision requirements.
  Routing redesign remains planned; these additions
  do not establish production, Windows or desktop-client qualification.

- **Guided draft client foundation (development preview).** `draft` commands and
  `mcp --guided` use explicit revisions, direct local YAML transfer and independent
  human approval references. Every operation requires a fresh versioned server
  capability; unsupported servers refuse before upload. Guided mode refuses legacy
  submission. This is not production/server qualification; Windows secure file IO
  remains pending. Guided job status/wait and generated-artifact downloads bind the
  job, draft revision and manifest; bounded streams verify length and SHA-256 before
  saving without overwriting. See [contract](docs/guided-workflows.md).

- **`whoami` never shows an organization's raw id (#685).** An organization with no name
  and no slug is listed as `(unnamed organization)` instead of its `org_…` id. The active
  organization and its membership entry are the same organization and show once, with the
  name if either entry carries one.

## 0.4.3 — 2026-10-23

- **Move between folders in the terminal app.** `/ls [FOLDER]` (or `/dir`) lists files and
  folders with sizes, folders first, hidden files left out; it never reads file contents.
  `/cd FOLDER` makes another folder the workspace (`~`, `..`, relative or absolute) and
  loads that folder's own remembered jobs; a missing or read-only folder is refused and
  nothing changes. `/pwd` shows the current folder. These are typed commands only: the
  model cannot choose them, and the MCP bridge keeps the `--workspace` it was started with.

## 0.4.2 — 2026-10-23

- **Running from a read-only folder no longer crashes.** Started from `/` (or any folder
  you can't write) without `--workspace`, the CLI uses `~/migrations`, the folder the
  installer creates, and says so on stderr. Before, first-run setup tried to create
  `/.netconverter` and stopped with `OSError: Read-only file system`. An explicit
  `--workspace` that can't be written is a one-line error. `login --key` from such a
  folder still stores the key and skips remembering the server there.
- **`mcp --strict` requests and verifies the server's strict view (#15).** The bridge sends
  `X-NetConverter-View: strict` on every remote request (the server may only lower the
  grant's view) and reads the view in force from `get_account`; `account` now reports
  `view_mode` and `strict_enforced_by` (`server`/`client`) next to the `strict_mode` flag.
  Until the server applies the strict view for the account, the bridge enforces it locally:
  `get_evidence section=unparsed_lines`, `get_job_brief focus=target` and any `fetch` that is
  not `kb:<doc_id>` are refused before any network call, every IPv4/IPv6 address or prefix in
  a remote result is masked as `<ip>`/`<cidr>`, and one stderr line says so. Names inside
  summaries are tokenised only by the server's strict view.
- **Linux: the bridge finds the keyring when the assistant hides the D-Bus bus (#17).**
  Codex, Cursor CLI and OpenClaw start MCP servers without `DBUS_SESSION_BUS_ADDRESS`, so
  the Clerk sign-in in the Secret Service was invisible and every tool said "not signed
  in". The client now points at `$XDG_RUNTIME_DIR/bus`, then `/run/user/<uid>/bus`, before
  keyring picks its backend. When no OS keyring is reachable, tool errors and the
  `netconverter mcp` startup line say `keyring_unreachable` and name the fix (set the bus
  address or `NETCONVERTER_API_KEY` in the assistant's MCP env) instead of "sign in".
- **One credential per `netconverter mcp` process (#16).** The bridge honours
  `NETCONVERTER_AUTH` (`NETCONVERTER_MCP_AUTH` still overrides it for `mcp` alone). In
  `auto` mode a Clerk sign-in is preferred and used for both the REST API and the remote
  tools; an API key from `NETCONVERTER_API_KEY` or the credential store is used only when
  chosen (`--auth key`) or when there is no sign-in, never for one surface while the
  sign-in serves the other. A startup line on stderr names the credential in use and the
  one left unused; `account` reports it as `credential_source`.
- **Refused requests show the server's reason (#22).** `APIError` now reads the External
  API's `error.message` (an older server's string `detail` too) and prints it, so
  `validate --vendor auto` says `unknown source_vendor 'auto'; valid: [...]` instead of a
  bare HTTP 422; MCP tool errors carry the same reason. `validate`/`analyze`/`optimize`/
  `convert` also check `--vendor` against the server's capabilities before uploading and
  list the valid source codes (there is no `auto`; detection lives in the guided flow).
- **`wait_for_job` fits a 60 s client tool timeout (#18).** The default `timeout_s` is 45
  (was 300; max still 600). A job still running when the wait ends comes back with
  `timed_out: true` and `next: "still running; call wait_for_job again …"` instead of the
  call being cut off by Codex or OpenClaw mid-job. Pass a larger `timeout_s` explicitly when
  the client allows a longer wait.

## 0.4.1 — 2026-10-22

- **First-run setup honours the Clerk sign-in (#6).** `NETCONVERTER_API_KEY` in the
  environment no longer skips the sign-in choice and is never copied into the OS keyring.
  `whoami` reports `api_key_stored` for the keyring only and adds `api_key_in_environment`.
- **Sign-in errors show Clerk's full reason.** The OAuth error description was cut at
  200 characters, hiding the cause sentence (e.g. a missing `device_code` grant, #684).
- **`whoami` shows one label per organization** (name, else slug) instead of the raw `org_...` id.

## 0.4.0 — 2026-10-21

- **On PyPI as `netconverter-cli`.** `uv tool install --python 3.12 netconverter-cli`
  installs the CLI; each tagged release is published from GitHub Actions with PyPI
  trusted publishing, and the wheel plus `SHA256SUMS` stay on the GitHub Release.
- **One-line installers.** `curl -LsSf https://netconverter.ai/install.sh | sh`
  (macOS/Linux) and `irm https://netconverter.ai/install.ps1 | iex` (Windows) install uv
  if needed and the CLI from PyPI (or the latest release wheel after its SHA-256 check
  when PyPI is unreachable), sign you in, create `~/migrations` and run
  `connect --all`. `--yes` for IT/MDM, `--no-connect`, `--workspace PATH`. Safe to run
  again. Sources: `scripts/install.sh`, `scripts/install.ps1`.
- **`netconverter update` follows the install.** A copy uv installed from PyPI is
  upgraded with `uv tool upgrade netconverter-cli`; a copy installed from a wheel keeps
  the verified-wheel path.
- **`netconverter --version`.**

## 0.3.2 — 2026-10-21

- **Safer Claude Code read rule.** `connect claude-code` no longer offers the
  `Read(//<folder>/**)` deny rule when the workspace is your home folder (or contains
  it): there it would stop Claude Code reading every project. Use a dedicated folder
  such as `~/migrations`.
- **`connect --all` skips optional extras** such as that rule; run
  `netconverter connect claude-code` on its own to review it.
- **Getting access guide** for new users and administrators: `docs/connect/getting-access.md`.

## 0.3.1 — 2026-10-21

- **More assistants.** `netconverter connect gemini` (Gemini CLI), `windsurf` and
  `lmstudio` merge the bridge into each client's MCP config, keeping every other key
  and a `.bak`, like `claude-desktop`.
- **ChatGPT and claude.ai.** `netconverter connect chatgpt` / `claude-ai` print the
  steps to add NetConverter's hosted MCP as a custom connector. Those apps cannot start
  a local program, so they read jobs, results and the knowledge base but do not submit
  files; nothing on the computer is changed.
- **`netconverter connect --all`** connects every local assistant found on this
  computer that is not connected yet, one prompt each (`--yes` for all). The list view
  now marks connected (●), found (○ found on this computer) and remote (↗) clients.

## 0.3.0 — 2026-10-20

- **Remote tool allowlist.** The bridge proxies a NetConverter MCP tool only when it
  is on the client's allowlist: the read tools the server advertises today plus the
  new `get_account`. A tool the server adds later, or any `submit_*` tool, is not
  offered to your AI until a client release lists it.
- **Strict mode.** `netconverter mcp --strict` (or `NETCONVERTER_MCP_STRICT=1`)
  proxies only the strict-view set: `list_jobs`, `select_job`, `get_account`, `search`,
  `fetch`, `kb_search`, `kb_explain`, `vendor_capability_lookup`, `get_job_brief`,
  `get_evidence`, `get_report`, whatever the server advertises. When your account is
  in the server's strict view mode, names in results arrive as `<name:…>` tokens.
- **New bridge tools.** `account` (tier, job types, rate limit, daily quota, auth kind,
  client version, `update_available`; no tokens or e-mail addresses) and
  `wait_for_job(job_id, timeout_s ≤ 600)`, which polls with backoff and returns the
  `job_status` summary plus `waited_s` and `timed_out`. It sends MCP progress
  notifications when the assistant asks for them. `job_status` also reports the job's
  stage and percentage when the server sends them. `submit_file` accepts
  `job_type: "analyze"` as an alias of validate.
- **`netconverter connect claude-desktop`** merges the bridge into Claude Desktop's
  `claude_desktop_config.json` (macOS and Windows), after showing a diff, with a `.bak`.
- **Claude Code read rule.** After `connect claude-code`, the CLI and the app offer
  (default yes) to add `Read(//<folder>/**)` to `permissions.deny` in
  `~/.claude/settings.json`, so Claude Code works on the folder's configurations
  through the bridge instead of reading them itself. See [privacy](docs/PRIVACY.md).
- **`netconverter update`** installs the latest GitHub release after verifying its
  SHA-256 against the release's `SHA256SUMS` (`--check` only reports, `--yes` skips
  the prompt). Interactive commands show a one-line notice at most once a day when
  a newer release exists; `NETCONVERTER_NO_UPDATE_CHECK=1` turns it off.

## 0.2.2 — 2026-10-19

- **Validate and optimize downloads keep the result.** `download` (bridge and app)
  saved only an empty `report.json` for these jobs; it now saves
  `<job>.validation.json` or `<job>.optimization.json` from the job's result, plus the
  evidence workbook when the server has one. An unfinished job answers
  `job_not_completed` instead of writing an empty file. Conversion downloads are unchanged.

## 0.2.1 — 2026-10-19

- **Your sign-in just works.** After `netconverter login --clerk`, plain commands
  (`capabilities`, `jobs`, `validate`, `convert`, …) and the app use it with no
  `NETCONVERTER_AUTH` variable; 0.2.0 prompted for an API key. A stored key is
  still used first, the sign-in only ever goes to a trusted NetConverter host, and
  `NETCONVERTER_AUTH=key|clerk` forces one. With neither, the command says how to
  connect instead of prompting.
- **First-run setup offers sign-in.** Plain `netconverter` in a new folder uses an
  existing sign-in, or asks: sign in with your NetConverter account (browser) or
  paste an API key. A workspace's `connection.json` still never chooses the credential.

## 0.2.0 — 2026-10-19

**NetConverter CLI.** The package is now `netconverter-cli` (the command is still
`netconverter`). Run `uv tool uninstall netconverter-terminal` before installing;
saved keys, sign-ins and workspace state carry over.

- **Every vendor the server supports.** Full-API keys and Clerk sign-ins use the
  External API: menus come from `GET /capabilities` (vendors, source → target paths,
  job types, limits), so firewalls, routers and switches all work and new server
  vendors need no client release. Terminal Quick pilot keys keep ASA → Palo Alto
  and are labelled as such.
- **`/validate` and `/optimize`** alongside `/convert`; the file's vendor is
  suggested from a local look at its first lines.
- **Redesigned app.** One-row header (server, bridge, model, allowance), cards with
  verdict badges, a bordered choice panel with a `▸` cursor and 1–9 jump keys, a
  bordered prompt, one status line with a spinner and progress bar, a contextual
  footer, readable labels instead of raw codes, and no wrapped review tables at 80 columns.
- **Your AI, visible.** `netconverter connect claude-code|cursor|vscode|codex` (or
  `/connect`) wires the bridge after showing the change. The bridge records metadata-only
  activity, shown live in the app and in `/activity`.
- **Bridge fixes.** Submissions send `technology` from the vendor code (router and
  switch jobs were labelled firewall). Validate/optimize work as soon as the server
  advertises them in `/me` (server change shipped alongside). Downloads add the
  evidence workbook.
- `netconverter capabilities`; `validate`/`convert --vendor … --to …` in plain mode.
  `login` and `setup` accept full-API keys (0.1.x checked only the pilot profile).

## 0.1.6 — 2026-10-18

- `netconverter login --clerk`: sign in with your NetConverter account (OAuth 2.1
  PKCE through clerk.netconverter.ai). `--device` for machines without a browser.
  Tokens live only in the OS credential store and refresh automatically.
  `netconverter whoami` and `netconverter logout` added. Key login is unchanged.
- `netconverter mcp`: a local MCP server for Claude Code, Cursor, VS Code and Codex.
  Your AI passes file paths; the client uploads the configuration directly to
  NetConverter, so the configuration never goes through the model. Tools:
  `submit_file`, `job_status`, `download`, plus the remote read-only NetConverter
  tools (evidence, NAT, flows, knowledge base).
- Your sign-in is only ever sent to api.netconverter.ai (or hosts you trust with
  `NETCONVERTER_TRUSTED_HOSTS`); a workspace file cannot redirect it.

## 0.1.5 — 2026-10-01

- Display server-authorized unlimited allowances as Unlimited in the status line
  and `/allowance`. This client update does not grant or change server entitlements.

## 0.1.4 — 2026-10-01

- Skip `evidence.json` and `pipeline-evidence.json` in automatic downloads and
  `/download`. Keep converted configs, YAML, reports and TXT/XLSX evidence.
- Existing local artifacts are not deleted. Follow-up query JSON/TXT is unchanged.

## 0.1.3 — 2026-10-01

- Replace modal forms, dropdowns and oversized buttons with compact inline
  keyboard questions: arrow keys choose, Enter continues, Esc cancels a choice.
- Disable mouse capture so normal terminal text selection works.
- `/convert` starts with an ASA source, then asks separately for Palo Alto output,
  server-supported options, cleanup and optional advanced overrides. Show the
  review before explicit job submission; uploads are separately confirmed.
- `/open`, `/analyze` and `/model` use the same inline flow. Keep keys masked and
  out of conversation history, preserve model connections on failed retries.
- A selected Palo Alto source now leads `/convert` to ASA file selection instead
  of leaving the user at a source-format validation error.
- Preserve server job status, warnings, downloads, privacy and no-clobber behavior.

## 0.1.2 — 2026-10-01

- Implement the approved NETCONVERTER.ai terminal design: compact welcome commands,
  persistent prompt/status, workspace file browser, readable jobs and local artifacts.
- File browser actions upload the selected config and open explicit conversion
  choices or submit analysis. ASA-only migration and the 50,000-byte limit remain.
- Replace raw JSON help and generic errors with readable commands and next steps.
- Add `/model` with hidden key entry, a synthetic compatibility probe, and retry
  without replacing a working model on failure. Setup distinguishes provider
  authentication, permissions, model access, quota, rate limits, and connectivity.
- Detect keys accidentally entered in the server URL field and reprompt.
- Display server progress/verdicts and hash-verified local downloads. Failed
  downloads remain retryable; existing outputs and source configurations survive.
- Responsive interaction coverage at 126×41 and 80×24; expanded negative tests.

Model protocol tests use mocks. The reported customer OpenAI connection failure
still needs live retesting with the customer's chosen API model. This release
does not add archive encryption, job cancellation, or a runtime guarantee.

## 0.1.1 — 2026-10-01

First public pilot client release under the MIT license.

- NetConverter branding and guided ASA → Palo Alto SET/XML/Panorama conversion.
- Production HTTPS setup, separate server/model credentials, and OS credential storage.
- Optional Anthropic, OpenAI, Gemini, and Ollama operation adapters.
- Analysis, optimization findings, structured policy questions, and revision selection.
- Server job IDs, resumable sessions, and verified artifacts beside the source.
- Customer installation, settings, privacy, troubleshooting, and uninstall guides.

This public repository begins with a reviewed client snapshot. Private development
history and server implementation are not included. See verification notes for
remaining acceptance work.
