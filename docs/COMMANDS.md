# Command and settings reference

Run `netconverter` in a configuration folder for the app.
`netconverter --help` lists plain CLI commands. Global options go **before** the
subcommand:

```sh
netconverter --workspace /path/to/configs run
netconverter --server https://api.netconverter.ai/external/v1 login
netconverter --provider ollama --model YOUR_INSTALLED_MODEL model-test
```

## App and plain mode

`netconverter` (or `netconverter run`) opens the app in the current folder.
`netconverter plain` opens a line prompt without the full-screen interface; give
commands their arguments there (`/open "edge.cfg" fortinet`).

| Command | Purpose |
| --- | --- |
| `/convert` | File → vendor → target → review → submit |
| `/validate` (`/analyze`) | Readiness, findings and parse gaps for a configuration |
| `/optimize` | Cleanup and optimization findings |
| `/open` | Choose a configuration without submitting |
| `/ls [FOLDER]` · `/dir` · `/cd FOLDER` · `/pwd` | List files (names and sizes) · work in another folder (`~`, `..`, relative or absolute; each folder keeps its own jobs) · show the current folder |
| `/jobs` · `/resume JOB_ID` · `/status` | List jobs · follow one · refresh the active job |
| `/download` | Save the active job's outputs beside its source, hash-verified |
| `/target` | Save the generated configuration and select it for `/validate` |
| `/nat` `/policy` `/routes` `/interfaces` `/unused_objects` | Summaries from the active job |
| `/dependencies {"object_name":"NAME"}` | Object dependency chain |
| `/flow {"source_ip":…,"destination_ip":…,"protocol":"tcp","destination_port":80}` | Which rule decides a flow |
| `/activity` · `/connect` | What your AI did through the bridge · wire an assistant |
| `/model` | Optional in-app model for plain-language questions |
| `/refresh` (`/allowance`) | Reconnect and reload capabilities and limits |
| `/help` · `/clear` · `/home` | Commands · clear · start card |

Questions need a completed job: use `/resume` first. Selecting another file or
`/target` clears the active job. Results are saved as JSON and TXT beside the source.

## Credentials and profiles

| Credential | Reaches | Vendors |
| --- | --- | --- |
| `netconverter login --clerk` (NetConverter account) | External API + NetConverter MCP | Everything `netconverter capabilities` lists |
| `netconverter login` with an `nck_…` API or trial key | External API (+ MCP when the key has `mcp:tools`) | Same; trial keys have trial limits |
| A 0.1.x Terminal Quick key | The pilot profile only | ASA → Palo Alto SET/XML/Panorama, 50,000 bytes |

The app shows the profile in the header and in `/refresh`.

Where a sign-in or key is kept: the OS credential store when one is available, otherwise
an encrypted credential file (headless machines, containers). `netconverter login --store
file` (or `keyring`, `auto`) chooses for that sign-in, for example `netconverter login
--device --store file` on an SSH host; `NETCONVERTER_CREDENTIAL_STORE=auto|keyring|file`
keeps the choice. The file needs a passphrase of at least 12 characters:
`NETCONVERTER_CREDENTIAL_PASSPHRASE`, `NETCONVERTER_CREDENTIAL_PASSPHRASE_FILE` (a path to a
file holding it), or a hidden prompt on a terminal. `NETCONVERTER_CREDENTIAL_FILE` moves the
file. `login` and `whoami` print the store in use. An AI client that starts `netconverter
mcp` must pass the passphrase variable in the server's `env`. Encryption details and the
threat model: [PRIVACY.md](PRIVACY.md#encrypted-credential-file-headless-machines).

## Conversion settings

Full API: choose the target; the server applies its defaults for everything else.
Pilot keys must also answer the Palo Alto settings the pilot API requires:

| Field | Meaning |
| --- | --- |
| `target_vendor` | A target from `netconverter capabilities` (e.g. `palo_alto_xml`, `fortinet`, `juniper_junos_router`) |
| `panos_target_version`, `routing_engine`, `pipeline_mode` | Pilot keys: PAN-OS version, `vr`/`lr`, `like_for_like`/`ai_recommended` |
| `panorama_device_group`, `panorama_template` | Pilot keys, Panorama target |
| `remove_unused_objects`, `enable_appid`, `app_id_implementation`, `add_security_profiles`, `log_all_rules`, `implicit_deny`, `default_profile_group`, `zone_mapping` | Pilot keys: optional overrides of the mode preset |

On the full API (`convert --options '{…}'`) the same settings are honoured too: the client
sends them as a YAML v2 decisions document (`zone_mapping`, `options`, `pa_target`,
`output_platform`), because the server ignores unknown body keys. `panos_target_version`,
`routing_engine` and `default_profile_group` apply to Palo Alto targets, the Panorama scope to
`palo_alto_panorama`, and `pipeline_mode` to pilot keys only; such a setting elsewhere, any
unknown key, or a request field (`source_config`, vendors, `technology`, `job_type`,
`manual_mappings`) is refused before anything is uploaded, naming it. The full API also accepts
`selected_device_groups`, `file_name`, `optimization_options` (optimize) and a whole `yaml_v2`.

In the app, `/convert` on the full API asks **Conversion settings** after the target: *Use
NetConverter's defaults* sends no decisions; *Customize* walks the same screens a pilot key
gets (Panorama scope for a Panorama target, unused-object cleanup, App-ID, profiles, logging,
explicit deny, a profile group for Palo Alto targets, and the zone mapping), each with a
server-default choice, and the review's Submit sends them as the YAML v2 document above.

### YAML v2 decisions (`yaml_v2`)

A conversion can carry a YAML v2 decisions document (zone mappings, interface
mappings and the other sections `GET /capabilities` lists under `schemas.yaml_v2`).
Pass it in `--options` as `"yaml_v2"`, either as YAML text or as a JSON object;
it applies to `convert` only, and the server checks it strictly (a typo'd section or
broken YAML is refused with its line and column, exit code 4). The limit is 1 MiB.

```sh
# YAML text from a file (jq builds the JSON string safely)
netconverter convert edge.cfg --vendor fortinet --to palo_alto_xml \
  --options "$(jq -Rs '{yaml_v2: .}' decisions.yaml)"
# or inline, as an object
netconverter convert edge.cfg --vendor fortinet --to palo_alto_xml \
  --options '{"yaml_v2": {"zone_mappings": {"inside": "Trust"}}}'
```

The MCP bridge's `submit_file` does not take `yaml_v2`: a decisions document is yours to
author and review, so it goes in through the terminal command above, never through the AI
conversation. Bridge `options` are the typed settings listed earlier, up to 16,000
characters of JSON.

## Plain CLI

These exit without polling. `convert`, `validate` / `analyze`, `optimize` and `resume` print a
short plain summary (verdict ready / needs review / blocked and why, counts, the first findings,
the next command); `--json` prints the raw API response instead and `--all` lists every finding.
The other commands print JSON.

```sh
netconverter capabilities
netconverter validate edge-fw.conf --vendor fortinet
netconverter convert edge-fw.conf --vendor fortinet --to palo_alto_xml
netconverter convert core.cfg --vendor cisco_ios_xe_router --to juniper_junos_router
netconverter jobs
netconverter resume JOB_ID
netconverter download
netconverter query nat
netconverter query unparsed_lines         # the configuration lines NetConverter could not parse
netconverter query flow --arguments '{"source_ip":"192.0.2.10","destination_ip":"198.51.100.10","protocol":"tcp","destination_port":80}'
netconverter connect                     # list assistants and whether they are connected
netconverter connect cursor --print      # show the change only
netconverter connect claude-desktop      # merge into claude_desktop_config.json (macOS, Windows)
netconverter connect --all               # every assistant found on this computer, one prompt each
netconverter connect chatgpt             # ChatGPT / claude.ai: prints remote-connector setup steps
netconverter mcp --workspace ~/migrations   # what an assistant runs; not for interactive use
netconverter mcp --level none --workspace ~/migrations   # lower this folder's level for one bridge
netconverter privacy status              # this folder's exposure level, what each level shows, recent changes
netconverter privacy level none          # verdicts and counts only (lowering needs no confirmation)
netconverter privacy level full          # raising asks you to type "raise to full" in a terminal
netconverter privacy level selected --sections nat,routes   # masked plus chosen sections
netconverter privacy apply --client claude-code   # deny the client's own file tools this folder (diff, then yes)
netconverter update --check              # is a newer release published? (--json for JSON)
netconverter update                      # verify and install it with uv, after a prompt
netconverter update --yes                # same, without the prompt
```

`connect` writes `netconverter mcp --workspace <folder>` with no view flag (0.4.4 wrote `--strict`): the
folder's exposure level decides what the assistant sees. Run `connect` again to drop an old `--strict`,
which would hold the assistant at masked after you raise the level.

### Exposure levels (`privacy`)

`netconverter privacy level LEVEL` sets what assistants connected to this folder may see; the
setting lives in `.netconverter/privacy.json` and every change is appended to
`.netconverter/privacy-audit.jsonl` (time, old → new, sections, user, folder, how it was confirmed).

| Level | The assistant gets |
| --- | --- |
| `none` | Verdicts, statuses, counts and ids only; every other value is removed and non-JSON text is withheld |
| `masked` (default) | The server's strict view (names as `<name:…>` tokens); addresses masked as `<ip>`/`<cidr>` by the bridge too; the strict tool set |
| `selected` | `masked`, plus the sections chosen with `--sections`: `interfaces`, `routes`, `policy`, `nat`, `vpn`, `objects`, `management`, `translation` (their summary tools), `unparsed_lines` (`get_evidence section=unparsed_lines`), `target` (`get_job_brief focus=target`, `get_target_config`), `reports` (`fetch` of job ids). Results stay masked; the server serves this level as strict until per-section un-tokenising ships |
| `full` | Results as the server serves them for your account (the 0.4.x `--full` view) |

Secrets (pre-shared keys, SNMP communities, password hashes, passwords) are removed from every
result at every level. Lowering works from scripts. Raising (a higher level, or adding a section)
needs the phrase `raise to LEVEL` typed in a terminal; from a pipe, a script or the MCP bridge it is
refused (exit 1). No MCP tool can read or change the level or its audit log.

**Precedence.** (1) The folder's level is the most any bridge for the folder serves. (2) `mcp --level
LEVEL` (alias `--view`), `--strict` (= masked) or `--full` (= full), else `NETCONVERTER_MCP_VIEW`, can
only lower it for that process; a flag beats the variable, and asking for more prints how to raise
the folder's level. (3) `--guided` serves at most masked and refuses `none`. (4) The bridge sends the
result as `X-NetConverter-View` on every request and the server applies min(your grant, level):
`none`/`masked`/`selected` as its strict view, `full` as its default view. Lowering the folder's
level takes effect on a running bridge's next call; a raise needs the assistant to list tools again.

`privacy apply --client CLIENT` keeps the client's own file tools out of the folder, so a
configuration reaches the model only through the bridge: `claude-code` (`Read(//<folder>/**)` and
`Edit(//<folder>/**)` in `~/.claude/settings.json`), `cursor` (`Read(<folder>/**)` and
`Write(<folder>/**)` in `~/.cursor/cli-config.json`), `gemini` (a deny policy for its file and shell
tools in `~/.gemini/policies/netconverter-<id>.toml`). Each shows a diff, applies after `y` (or
`--yes`), keeps a `.bak` and changes nothing on a second run; `--print` only shows it. `codex`
(a permission profile with `"<folder>" = "deny"`) and `openclaw` (`tools.deny`,
`tools.fs.workspaceOnly`, `sandbox.workspaceAccess`) print the settings to add yourself, because
they change the client's active profile or policy. Start every client outside the folder: one started
in it or a parent can reach the files through its project tools.

`connect` targets: `claude-code` (through `claude mcp add`, user scope; then offers
a `Read(//<folder>/**)` deny rule in `~/.claude/settings.json`, default yes),
`claude-desktop`, `cursor`, `vscode` (this folder's `.vscode/mcp.json`), `codex` (with
`env_vars` forwarding the NetConverter variables), `gemini` (Gemini CLI,
`~/.gemini/settings.json`, with an `env` block of `$NAME` references because Gemini strips
variables named like KEY/AUTH/CREDENTIAL; trust the folder in Gemini or no MCP server
starts), `devin` (Devin Desktop, formerly Windsurf, and Devin CLI:
`~/.config/devin/mcp_config.json`), `windsurf` (legacy Cascade,
`~/.codeium/windsurf/mcp_config.json`) and `lmstudio` (`~/.lmstudio/mcp.json`). Paths and
formats per vendor docs: [connect/compatibility.md](connect/compatibility.md).
`chatgpt` and `claude-ai` only reach remote MCP servers, so `connect` prints the steps
to add NetConverter's hosted MCP (`https://api.netconverter.ai/mcp/v1`) in that app and
changes nothing locally; those apps read jobs, results and the knowledge base but cannot
submit files. `--all` connects every local assistant whose config folder exists and that
is not connected yet. `--print` shows every change without writing; `--yes` applies all of them.

`update` reads the latest release of `valeronlabs/netconverter_terminals` from the
public GitHub API, downloads the wheel and `SHA256SUMS` to a temporary folder,
installs only when the SHA-256 matches, and runs `uv tool install --force <wheel>`.
Without `uv` on PATH it prints the steps instead and exits 1.
Interactive commands (not `mcp`, and only when stderr is a terminal) check at most
once a day in the background, with a 3-second timeout, and print a one-line notice
on stderr on a later run when a newer release exists. The check never fails or
delays a command; its result is cached in your user cache folder.

## MCP bridge tools

| Tool | Returns |
| --- | --- |
| `submit_file(path, source_vendor, target_vendor?, job_type?, options?)` | `job_id`, `status`, `sha256`, `bytes`. `job_type`: `convert`, `validate`, `optimize`, or `analyze` (= validate). `options` keys (typed; anything else is refused naming it): `selected_device_groups`, `file_name`, `optimization_options` (optimize), and for convert `zone_mapping`, `remove_unused_objects`, `enable_appid`, `app_id_implementation`, `add_security_profiles`, `log_all_rules`, `implicit_deny`, `panos_target_version` / `routing_engine` / `default_profile_group` (Palo Alto targets), `panorama_device_group` / `panorama_template` (Panorama), `pipeline_mode` (pilot keys). On the full API the convert settings travel as a `yaml_v2` decisions document |
| `job_status(job_id)` | Status, verdict, review flag, progress and stage when sent, reason counts, vendors |
| `wait_for_job(job_id, timeout_s=45)` | The `job_status` summary plus `waited_s` and `timed_out` (plus `next` when still running: call it again); polls 2 s, ×1.5, up to 15 s apart, at most 600 s. The default stays under the 60 s tool timeout of Codex and OpenClaw; pass a larger `timeout_s` only when the client allows it. Sends MCP progress notifications when the call has a progress token |
| `account()` | Signed out: `status` (`signed_out`, `keyring_unreachable`), `signed_in: false`, `message`, `client_version`, `update_available`, `latest_version` (not an error). Signed in: `tier`, `job_types`, `rate_limit_per_min`, `daily_quota`, `auth_kind`, `profile`, `client_version`, `update_available`, `latest_version`, `strict_mode` (true below `full`), `exposure_level` and `exposure_sections` (the level in force, see Exposure levels), `view_mode_grant` and `view_clamped` when the server reports them, `view_mode` (the view the server applies to this session, from `get_account`), `strict_enforced_by` (`server` when that view is strict, `client` while the bridge enforces it locally), `credential_source` (`clerk_session`, `api_key_environment`, `api_key_stored` or `none`; the one credential REST and the remote tools share) |
| `download(job_id, dest_dir=".")` | Saved file names, sizes and SHA-256 |

Every local tool declares an `outputSchema` for its `structuredContent` (error results carry
none). When the assistant advertises form elicitation in `initialize` (Claude Code, Codex, Cursor
CLI), `submit_file` first asks in the assistant's own dialog: "Upload <path> (<bytes>, SHA-256 …) to
NetConverter for <job type>?". Accept uploads; Decline or a dismissed dialog sends nothing and the
tool returns `upload_declined`. Without elicitation, or when the assistant answers the request with
an error, the upload proceeds after the assistant's own tool approval, as before. The dialog shows
the path, size and hash only, never the file's text.

The bridge also offers two MCP prompts: `guided-migration` (from a file path to a verdict and
artifacts) and `mapping-review` (optional `job_id`: what was mapped, what needs review, what is
blocked). Both tell the assistant it will not get configuration content and name the folder's
exposure level. `--guided` keeps its own prompts (`migration-studio`, `pre-cutover-review`).

Remote NetConverter tools are proxied only from a fixed allowlist, and never a
`submit_*` tool. Default: `compare_against_intent`, `fetch`, `get_account`,
`get_acl_summary`, `get_critical_object_impact`, `get_dependency_chains`,
`get_evidence`, `get_interface_summary`, `get_job_brief`, `get_management_config`,
`get_nat_summary`, `get_object_dependencies`, `get_object_summary`, `get_report`,
`get_route_summary`, `get_target_config`, `get_translation_edge_summary`,
`get_unused_objects`, `get_vpn_summary`, `get_zone_summary`, `kb_explain`,
`kb_search`, `list_jobs`, `list_objects_with_attribute`, `list_rules_matching`,
`query_ir`, `search`, `select_job`, `simulate_flow`, `vendor_capability_lookup`.
At levels `none`, `masked` and `selected` (the default is masked; `full` uses the default list):
`list_jobs`, `select_job`, `get_account`, `search`, `fetch`,
`kb_search`, `kb_explain`, `vendor_capability_lookup`, `get_job_brief`,
`get_evidence`, `get_report`, plus the chosen sections' tools under `selected`. A listed tool appears
only if the server offers it.
The bridge sends the level on every request (`X-NetConverter-View: none|masked|selected|full`;
the server may only lower the grant's view, never raise it) and reads the view in force from
`get_account`. Until the server applies it, the bridge enforces strict locally: it refuses
`get_evidence section=unparsed_lines`, `get_job_brief focus=target` and any `fetch` that is not
`kb:<doc_id>` before any network call, masks every IPv4/IPv6 address and prefix in remote results
as `<ip>`/`<cidr>`, and says so once on stderr. Names in summaries are tokenised only by the
server's strict view; `account` reports which side is enforcing.

Global options go before the subcommand: `netconverter --workspace DIR --server URL …`.
Environment: `NETCONVERTER_URL`, `NETCONVERTER_PROVIDER`, `NETCONVERTER_MODEL`,
`NETCONVERTER_AUTH=key` or `=clerk` (force one credential; unset, plain commands use a stored key first, then
your sign-in, while `mcp` prefers the sign-in and says on stderr which API key it leaves unused;
`NETCONVERTER_MCP_AUTH` overrides it for `mcp` only), `NETCONVERTER_TRUSTED_HOSTS`, `NETCONVERTER_MCP_VIEW=none|masked|selected|full|strict` (same as `mcp --level`; it can only lower
the folder's exposure level, and an explicit flag wins),
`NETCONVERTER_NO_UPDATE_CHECK=1` (no daily update check or notice; `account` then reports
`update_available: null`), `NETCONVERTER_KEYRING_TIMEOUT_S` (how long to wait for the OS keyring
before reporting it locked; default 5), `NETCONVERTER_CREDENTIAL_STORE`,
`NETCONVERTER_CREDENTIAL_PASSPHRASE`, `NETCONVERTER_CREDENTIAL_PASSPHRASE_FILE` and
`NETCONVERTER_CREDENTIAL_FILE` (the encrypted credential file; see Credentials and profiles).
Never put a literal key in shell history or a shared script.

## Exit codes

Plain commands print results on stdout and every error on stderr, as one
sentence that names the reason (the server's own reason when it sent one).

| Code | Meaning |
| --- | --- |
| `0` | Success |
| `1` | The command ran but did not succeed (a change was not applied, an update or model check failed) |
| `2` | Usage: unknown command or option, missing or unknown `--vendor` |
| `3` | Sign-in: not signed in, sign-in rejected or the keyring is locked, or the credential lacks the entitlement (HTTP 401/403) |
| `4` | Input refused: a missing, empty, oversized or out-of-workspace file, malformed `--options`, or the server's 400/404/409/413/422 reason |
| `5` | NetConverter unreachable or failing: connection error, HTTP 429, 5xx |
| `130` | Cancelled with Ctrl-C ("Cancelled. Nothing was saved.") |

Local checks (the file and `--options`) run before the sign-in, so a missing
file is reported as a missing file, never as "not signed in".

## Troubleshooting

| Symptom | Action |
| --- | --- |
| `netconverter` not found | Run `uv tool update-shell`, open a new Terminal, then `netconverter --help` |
| Setup suggests localhost | Run `netconverter --server https://api.netconverter.ai/external/v1 setup` to replace earlier demo settings |
| 401 / invalid key | Rerun `login`; verify your issued key, its server, and whether it was revoked |
| 403 / restricted access | The credential lacks that permission (for example a pilot key on a non-ASA source); `netconverter capabilities` shows what it can do |
| 413 / file too large | Check `wc -c FILE` against the limit in `/refresh` (5 MB full API, 50 KB trial and pilot keys) |
| 422 / required decisions | Complete the indicated conversion fields using the server's supported choices |
| 429 / quota or active job | Check `/refresh` and `/jobs`; resume the existing active job or wait for the UTC daily reset |
| Model unavailable or forbidden operation | Continue using guided commands; use `/model` to retry with an accessible model; errors distinguish key, access, quota, rate limit, timeout, and tool incompatibility |
| Ollama connection fails | Start the local Ollama service and select an already installed tool-capable model; no hosted fallback is attempted |
| File not listed | Hidden files, downloaded outputs and binary types are skipped; choose **Type a relative file path** |
| "does not publish its capabilities" | The server predates 0.2.0; ask NetConverter, or use a pilot key meanwhile |
| Out-of-workspace path | Launch from a suitable containing folder or place a deliberate copy inside the workspace; escaping symlinks are rejected |
| Submit interrupted | Keep workspace state and use `/resume`; do not start a duplicate conversion |
| Download fails or hash mismatch | Retry `/download`; if persistent, retain the job ID and contact support |
| Existing output differs | Preserve your edited file by renaming/moving it, then retry; the client refuses to overwrite it |
| No verified configuration | Read validation reports and warnings; evidence can be available even when no deployable output is produced |
| Proxy-only network fails | Client HTTP connections ignore environment proxy settings and do not follow redirects; use a network with direct access to configured endpoints |
| Full-screen UI unsuitable | Use `netconverter plain` or individual CLI commands |
| "the credentials are in the encrypted file …, which this process cannot open" | Set `NETCONVERTER_CREDENTIAL_PASSPHRASE` (or `NETCONVERTER_CREDENTIAL_PASSPHRASE_FILE`) to the passphrase used at sign-in, in the shell or in the AI client's `env` for the bridge. "does not open" means a wrong passphrase or an altered file |
| "Your system keyring is locked" (exit 3) | The OS keyring did not answer within 5 seconds (a locked Secret Service collection after a reboot, or a keychain waiting for a password). Unlock it (for example by logging in to the desktop session), or sign in again with `netconverter login` |
| `keyring_unreachable` from the bridge (Linux) | The assistant launched `netconverter mcp` without `DBUS_SESSION_BUS_ADDRESS`; the bridge tries `$XDG_RUNTIME_DIR/bus` and `/run/user/<uid>/bus`, else set that variable (or `NETCONVERTER_API_KEY`) in the assistant's MCP server environment and restart it |
| Assistant cannot see a NetConverter tool | The bridge lists only allowlisted remote tools the server offers (fewer below `full`; `netconverter privacy status` shows the level); update the client with `netconverter update` |
| `netconverter update` says uv is not on PATH | Install uv, or follow the printed download, `shasum -a 256 -c SHA256SUMS` and `uv tool install --force` steps |

Use the server job ID and client version when asking for help. Do not attach
real configurations, credentials, object names, addresses, or unredacted reports
to public issues. Redacted reproductions with synthetic data are preferred.
