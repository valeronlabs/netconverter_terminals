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
| `/jobs` · `/resume JOB_ID` · `/status` | List jobs · follow one · refresh the active job |
| `/download` | Save the active job's outputs beside its source, hash-verified |
| `/target` | Save the generated configuration and select it for `/validate` |
| `/nat` `/policy` `/routes` `/interfaces` `/unused_objects` | Summaries from the active job |
| `/dependencies {"object_name":"NAME"}` | Object dependency chain |
| `/flow {"source_ip":…,"destination_ip":…,"protocol":"tcp","destination_port":80}` | Which rule decides a flow |
| `/activity` · `/connect` | What your AI did through the bridge · wire an assistant |
| `/model` | Optional in-app model for plain-language questions |
| `/allowance` | Refresh capabilities and limits |
| `/help` · `/clear` · `/home` | Commands · clear · start card |

Questions need a completed job: use `/resume` first. Selecting another file or
`/target` clears the active job. Results are saved as JSON and TXT beside the source.

## Credentials and profiles

| Credential | Reaches | Vendors |
| --- | --- | --- |
| `netconverter login --clerk` (NetConverter account) | External API + NetConverter MCP | Everything `netconverter capabilities` lists |
| `netconverter login` with an `nck_…` API or trial key | External API (+ MCP when the key has `mcp:tools`) | Same; trial keys have trial limits |
| A 0.1.x Terminal Quick key | The pilot profile only | ASA → Palo Alto SET/XML/Panorama, 50,000 bytes |

The app shows the profile in the header and in `/allowance`.

## Conversion settings

Full API: choose the target; the server applies its defaults for everything else.
Pilot keys must also answer the Palo Alto settings the pilot API requires:

| Field | Meaning |
| --- | --- |
| `target_vendor` | A target from `netconverter capabilities` (e.g. `palo_alto_xml`, `fortinet`, `juniper_junos_router`) |
| `panos_target_version`, `routing_engine`, `pipeline_mode` | Pilot keys: PAN-OS version, `vr`/`lr`, `like_for_like`/`ai_recommended` |
| `panorama_device_group`, `panorama_template` | Pilot keys, Panorama target |
| `remove_unused_objects`, `enable_appid`, `app_id_implementation`, `add_security_profiles`, `log_all_rules`, `implicit_deny`, `default_profile_group`, `zone_mapping` | Pilot keys: optional overrides of the mode preset |

## Plain CLI

These print JSON and exit; they do not poll.

```sh
netconverter capabilities
netconverter validate edge-fw.conf --vendor fortinet
netconverter convert edge-fw.conf --vendor fortinet --to palo_alto_xml
netconverter convert core.cfg --vendor cisco_ios_xe_router --to juniper_junos_router
netconverter jobs
netconverter resume JOB_ID
netconverter download
netconverter query nat
netconverter query flow --arguments '{"source_ip":"192.0.2.10","destination_ip":"198.51.100.10","protocol":"tcp","destination_port":80}'
netconverter connect                     # list assistants and whether they are connected
netconverter connect cursor --print      # show the change only
netconverter mcp --workspace ~/migrations   # what an assistant runs; not for interactive use
```

Global options go before the subcommand: `netconverter --workspace DIR --server URL …`.
Environment: `NETCONVERTER_URL`, `NETCONVERTER_PROVIDER`, `NETCONVERTER_MODEL`,
`NETCONVERTER_AUTH=key` or `=clerk` (force one credential; unset, a stored key is used first, then
your sign-in), `NETCONVERTER_TRUSTED_HOSTS`.
Never put a literal key in shell history or a shared script.

## Troubleshooting

| Symptom | Action |
| --- | --- |
| `netconverter` not found | Run `uv tool update-shell`, open a new Terminal, then `netconverter --help` |
| Setup suggests localhost | Run `netconverter --server https://api.netconverter.ai/external/v1 setup` to replace earlier demo settings |
| 401 / invalid key | Rerun `login`; verify your issued key, its server, and whether it was revoked |
| 403 / restricted access | The credential lacks that permission (for example a pilot key on a non-ASA source); `netconverter capabilities` shows what it can do |
| 413 / file too large | Check `wc -c FILE` against the limit in `/allowance` (5 MB full API, 50 KB trial and pilot keys) |
| 422 / required decisions | Complete the indicated conversion fields using the server's supported choices |
| 429 / quota or active job | Check `/allowance` and `/jobs`; resume the existing active job or wait for the UTC daily reset |
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

Use the server job ID and client version when asking for help. Do not attach
real configurations, credentials, object names, addresses, or unredacted reports
to public issues. Redacted reproductions with synthetic data are preferred.
