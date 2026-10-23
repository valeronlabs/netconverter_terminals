# Changelog

## Unreleased

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
