# Quick start (Mac)

Use synthetic configurations for your first run, and read the
[privacy notes](docs/PRIVACY.md) before using real ones.

## 1. Install

```sh
curl -LsSf https://netconverter.ai/install.sh | sh
```

This installs uv and `netconverter-cli` from PyPI, signs you in, creates
`~/migrations` and offers to connect each AI assistant it finds (steps 2 and 6 below).
Add `--no-connect` (`… | sh -s -- --no-connect`) to only install and sign in.

By hand:

```sh
brew install uv                      # if `uv --version` fails
uv tool install --python 3.12 netconverter-cli
uv tool update-shell                 # then open a new Terminal window
netconverter --version
```

Without PyPI access, download `netconverter_cli-<version>-py3-none-any.whl` and
`SHA256SUMS` from the [latest release](https://github.com/valeronlabs/netconverter_terminals/releases/latest),
run `shasum -a 256 -c SHA256SUMS` (stop if it fails), then
`uv tool install --python 3.12 ./netconverter_cli-<version>-py3-none-any.whl`.

Coming from 0.1.x? Run `uv tool uninstall netconverter-terminal` first. Your
saved key, sign-in and per-folder `.netconverter/` state are kept.

## 2. Sign in

```sh
netconverter login --clerk           # NetConverter account in the browser (MFA, SSO)
netconverter login --clerk --device  # same, on a machine without a browser
netconverter login                   # or paste an API key / trial key, hidden
netconverter whoami
netconverter capabilities            # what your credential can convert
```

After `login --clerk`, every command and the app use your sign-in; no key and no environment
variable are needed. A stored API key, if you also have one, is used first.
Credentials live in the macOS Keychain (service **NetConverter Terminal**), never
in the workspace folder. A 0.1.x Terminal Quick pilot key keeps working with its
ASA → Palo Alto scope.

## 3. Run the app in your config folder

```sh
mkdir -p ~/NetConverter-Demo && cd ~/NetConverter-Demo
cp /path/to/examples/demo-asa.cfg .
netconverter
```

The folder you start in is the workspace. Nothing is uploaded when the app opens.

| Key | Does |
| --- | --- |
| `↑` `↓` / `1`–`9` | Move / jump to a choice |
| `Enter` | Continue |
| `Esc` | Cancel the open question (never a submitted job) |
| `Ctrl+O` · `Ctrl+J` · `Ctrl+R` | Open a file · jobs · refresh the active job |
| `F1` · `Ctrl+Q` | Help · quit |

## 4. Convert

1. Type `/convert` and pick the file.
2. **What does it contain?** The likely vendor is pre-selected from a local
   look at the file (marked *detected*); confirm or choose another.
3. **Convert to** lists only the targets the server supports for that source.
4. Review the card and choose **Submit to NetConverter**. This is the moment
   the file is sent, and it uses one conversion.
5. Follow the job in the status line. When it completes, the outputs download
   beside the source, hash-verified:

```text
tra_….translated.txt      converted configuration
tra_….report.json         structured verdict, findings and reasons
tra_….evidence.xlsx       evidence workbook, when the job has one
```

Read warnings before using an output. `NEEDS REVIEW` and `BLOCKED` are set by
deterministic checks, not by AI.

## 5. Validate, optimize, ask

- `/validate` and `/optimize` follow the same file → vendor → review steps.
- After a job completes: `/nat`, `/policy`, `/routes`, `/interfaces`,
  `/unused_objects`, and structured questions such as
  `/flow {"source_ip":"192.0.2.10","destination_ip":"198.51.100.10","protocol":"tcp","destination_port":80}`.
  Results are saved as JSON and TXT beside the source.
- `/target` saves the generated configuration and selects it, so you can `/validate` it.

## 6. Connect your AI assistant

```sh
netconverter connect                 # which assistants are already connected
netconverter connect claude-code     # shows the change, asks, then applies
netconverter connect claude-desktop  # Claude Desktop: merges its config file, keeps a .bak
netconverter connect --all           # every assistant found here (Gemini CLI, Cursor, Codex …)
netconverter connect chatgpt         # ChatGPT or claude.ai: prints the remote-connector steps
```

Or `/connect` inside the app. For Claude Code, `connect` then offers a second
change (Enter accepts): a `Read(//…/**)` deny rule for this folder in
`~/.claude/settings.json`, so Claude Code hands files to the bridge by path instead
of reading them itself. Restart Claude Code or Claude Desktop afterwards. Then ask your assistant to validate or convert a file
by name. `/activity` shows each call the bridge handled: time, assistant, file,
size, SHA-256 and job ID — never content.

## 7. Resume, update, uninstall

- Quit with `Ctrl+Q`; run `netconverter` in the same folder to continue.
  `/jobs` lists your jobs; `/resume JOB_ID` follows one. An interrupted submit is
  retried by `/resume` with the same idempotency key, so it is not duplicated.
- Update: `netconverter update` runs `uv tool upgrade netconverter-cli` for a PyPI
  install; for a copy installed from a wheel it downloads the latest release's wheel
  and `SHA256SUMS`, checks the hash and runs `uv tool install --force` after you
  confirm (`--check` only reports). Interactive commands mention a new release at most once
  a day; `NETCONVERTER_NO_UPDATE_CHECK=1` turns that off. Manual route: verify the
  new wheel, then `uv tool install --force ./netconverter_cli-….whl`.
- Remove: `uv tool uninstall netconverter-cli`. Configs, outputs, Keychain entries
  and `.netconverter/` folders stay until you delete them; `netconverter logout --all`
  removes the saved sign-in and key.

Something failed? See [troubleshooting](docs/COMMANDS.md#troubleshooting).
