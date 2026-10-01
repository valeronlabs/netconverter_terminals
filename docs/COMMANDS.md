# Command and settings reference

Run `netconverter` or `netconverter run` in a configuration folder for the TUI.
`netconverter --help` lists plain CLI commands. Global options go **before** the
subcommand:

```sh
netconverter --workspace /path/to/configs run
netconverter --server https://api.netconverter.ai/external/v1 login
netconverter --provider ollama --model YOUR_INSTALLED_MODEL model-test
```

## TUI and interactive plain mode

`netconverter plain` opens a prompt without the full-screen interface. Use `/help`
and `/quit`. In the TUI, bare `/open`, `/convert`, and `/model` open forms; in plain mode,
provide their arguments as shown below.

| Command | Purpose |
| --- | --- |
| `/open "file.cfg" cisco_asa` | Upload a selected file and bind the source revision |
| `/analyze` | Submit analysis for the selected source or target |
| `/optimize` | Request supported optimization findings |
| `/convert {…}` | Submit explicit conversion settings |
| `/model` (TUI) | Test or repair a model connection with a masked key field |
| `/home`, `/clear` (TUI) | Return to the welcome screen; clear also clears visible history |
| `/jobs` | List accessible server jobs |
| `/resume JOB_ID` | Select a job and fetch status; no argument retries pending work or the active job |
| `/status` | Fetch authoritative server status |
| `/target` | Select the active conversion's verified generated target for a new analysis |
| `/download` | Retrieve available artifacts for the active job |
| `/allowance` | Refresh capabilities and remaining daily allowance |
| `/unused_objects` | Return unused-object findings and reasons |
| `/routes` | Return supported routing findings/recommendations |
| `/interfaces`, `/policy`, `/nat` | Inspect the corresponding supported findings |
| `/dependencies {"object_name":"DEMO_UNUSED"}` | Query an explicitly named object |
| `/flow {"source_ip":"192.0.2.10","destination_ip":"198.51.100.10","protocol":"tcp","destination_port":80}` | Ask a specific traffic-policy question |

Palo Alto source vendors: `palo_alto_set`, `palo_alto_xml`,
`palo_alto_panorama`. Conversion remains ASA → Palo Alto only.
Questions require an appropriate completed job. Selecting a different source or
`/target` clears the active job, so analyze that revision before querying it.
The client retrieves complete paginated findings and saves query results as JSON
and TXT beside the source. Tables may show abbreviated previews; use the saved
files for the complete detail.

Natural-language questions require a configured model. Models can request only a
fixed operation. Detailed arguments and migration decisions remain explicit user
inputs. `/optimize` recommendations do not by themselves produce a cleaned config.
Unused-object results describe structural references, not observed traffic hits;
review the reason and coverage before removing anything.

The welcome commands are clickable. **Ctrl+O** opens the file browser, **Ctrl+R**
refreshes status, **F1** shows help, and **Ctrl+Q** exits. Job history includes local
source/target/submission metadata when available; missing values remain blank.
Server polling supplies progress and verdicts. The client does not invent an ETA,
raw engine logs, cancellation support, or encrypted output archives. Downloads
show actual local filenames, sizes, and directories after hash verification.

## Conversion settings

Required choices come from live server capabilities. The following field names
are also available through JSON in plain mode; the server validates every request.

| Field | Meaning |
| --- | --- |
| `target_vendor` | `palo_alto_set`, `palo_alto_xml`, or `palo_alto_panorama` |
| `panos_target_version` | Explicit supported target PAN-OS version |
| `routing_engine` | `vr` or `lr`, as supported by the target |
| `pipeline_mode` | `like_for_like` or `ai_recommended`, as offered by the service |
| `panorama_device_group`, `panorama_template` | Required for Panorama |
| `remove_unused_objects` | Boolean; validated migration cleanup; form defaults to false |
| `enable_appid` | Optional Boolean override of the mode preset |
| `app_id_implementation` | `dual_stack` (stack above original) or `force` (replace original) |
| `add_security_profiles` | Optional Boolean override |
| `log_all_rules` | Optional Boolean override |
| `implicit_deny` | String `explicit-deny-all` or `none`, not a Boolean |
| `default_profile_group` | Optional security profile group name |
| `zone_mapping` | JSON object mapping source zone names to target zone names |

Example only—choose values for your target using `/allowance` or the TUI:

```text
/convert {"target_vendor":"palo_alto_set","panos_target_version":"11.2","routing_engine":"lr","pipeline_mode":"like_for_like","remove_unused_objects":false}
```

The client does not invent missing choices. Invalid requests return missing or
invalid fields and do not use a job allowance. Accepted requests count once,
including work that later fails. Generating SET, XML, and Panorama consumes three
conversion allowances; the client submits one target per request.

## Plain CLI examples

These commands run from the same workspace after setup. They print JSON, submit
work, or fetch one response and exit; they do not continuously poll.

```sh
netconverter analyze demo-asa.cfg --vendor cisco_asa
netconverter jobs
netconverter resume YOUR_ANALYSIS_JOB_ID
netconverter query unused_objects
netconverter query flow --arguments '{"source_ip":"192.0.2.10","destination_ip":"198.51.100.10","protocol":"tcp","destination_port":80}'
netconverter convert demo-asa.cfg --options '{"target_vendor":"palo_alto_set","panos_target_version":"11.2","routing_engine":"lr","pipeline_mode":"like_for_like"}'
netconverter resume trm_YOUR_JOB_ID
netconverter download
netconverter allowance
netconverter ask 'Find unused objects'
```

For `query` and `download`, resume/select the intended completed job first.
`ask` needs the selected model; direct commands do not.
`netconverter plain '/target'` selects a verified target, then
`netconverter plain '/analyze'` analyzes it without uploading another local file.
`netconverter optimize demo-asa.cfg` requests optimization findings.

Environment variables can supply server/provider preferences:
`NETCONVERTER_URL`, `NETCONVERTER_PROVIDER`, and `NETCONVERTER_MODEL`.
Secret environment overrides are also supported, but hidden setup prompts and the
OS credential store are preferred. Never put a literal key in shell history or a
shared script. Explicit CLI preferences take precedence over saved preferences.

## Troubleshooting

| Symptom | Action |
| --- | --- |
| `netconverter` not found | Run `uv tool update-shell`, open a new Terminal, then `netconverter --help` |
| Setup suggests localhost | Run `netconverter --server https://api.netconverter.ai/external/v1 setup` to replace earlier demo settings |
| 401 / invalid key | Rerun `login`; verify your issued key, its server, and whether it was revoked |
| 403 / restricted access | Confirm terminal pilot enrollment and `terminal_quick` key; an ordinary API key is not equivalent |
| 413 / file too large | Keep the source at or below 50,000 bytes; use `wc -c FILE`; contact NetConverter for larger migrations |
| 422 / required decisions | Complete the indicated conversion fields using the server's supported choices |
| 429 / quota or active job | Check `/allowance` and `/jobs`; resume the existing active job or wait for the UTC daily reset |
| Model unavailable or forbidden operation | Continue using guided commands; use `/model` to retry with an accessible model; errors distinguish key, access, quota, rate limit, timeout, and tool incompatibility |
| Ollama connection fails | Start the local Ollama service and select an already installed tool-capable model; no hosted fallback is attempted |
| File not listed | Use the relative path field inside the workspace; supported picker extensions are asa/cfg/conf/txt/set/xml |
| Out-of-workspace path | Launch from a suitable containing folder or place a deliberate copy inside the workspace; escaping symlinks are rejected |
| Submit interrupted | Keep workspace state and use `/resume`; do not start a duplicate conversion |
| Download fails or hash mismatch | Retry `/download`; if persistent, retain the job ID and contact support |
| Existing output differs | Preserve your edited file by renaming/moving it, then retry; the client refuses to overwrite it |
| No verified configuration | Read validation reports and warnings; evidence can be available even when no deployable output is produced |
| Proxy-only network fails | Client HTTP connections ignore environment proxy settings and do not follow redirects; use a network with direct access to configured endpoints |
| Full-screen UI unsuitable | Use `netconverter plain` or individual CLI commands |

Use the server job ID and client version when asking for help. Do not attach
real configurations, credentials, object names, addresses, or unredacted reports
to public issues. Redacted reproductions with synthetic data are preferred.
