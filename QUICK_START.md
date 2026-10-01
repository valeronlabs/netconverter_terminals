# First run on a Mac

This guide installs the client from the public release and connects directly to
the NetConverter service. Use synthetic configurations for initial pilot testing;
read the [privacy and verification notes](docs/PRIVACY.md) before using sensitive data.

## 1. Get the two connections ready

**Required:** a NetConverter API key issued for the `terminal_quick` pilot profile.
Ask your NetConverter contact for enrollment and a dedicated terminal key. A normal
appliance/API key may not have these permissions. Keep the key private.

**Optional:** a model provider and exact model ID, plus its API key if using
Anthropic, OpenAI, or Gemini. These are separate credentials from the NetConverter
key. A consumer chat subscription is not configured by this client. You can select
`none` and perform the complete guided conversion without a model.

For local inference, start your existing Ollama service and use an installed model
that supports the required tool protocol. The client does not install Ollama,
download weights, or fall back to a hosted provider. Setup tests compatibility.

## 2. Install uv and the client

Open **Terminal** on your Mac. If uv is already installed, check it:

```sh
uv --version
```

If it is missing and you use Homebrew:

```sh
brew install uv
```

For other installation methods, follow the official [uv installation guide](https://docs.astral.sh/uv/getting-started/installation/).
The client requires Python 3.12 or newer. uv can install the required interpreter:

```sh
uv python install 3.12
```

Download the wheel and checksums from the [v0.1.2 release](https://github.com/valeronlabs/netconverter_terminals/releases/tag/v0.1.2),
or run:

```sh
mkdir -p ~/Downloads/netconverter-terminal-0.1.2
cd ~/Downloads/netconverter-terminal-0.1.2
curl --fail --location --remote-name https://github.com/valeronlabs/netconverter_terminals/releases/download/v0.1.2/netconverter_terminal-0.1.2-py3-none-any.whl
curl --fail --location --remote-name https://github.com/valeronlabs/netconverter_terminals/releases/download/v0.1.2/SHA256SUMS
shasum -a 256 -c SHA256SUMS
uv tool install --python 3.12 ./netconverter_terminal-0.1.2-py3-none-any.whl
uv tool update-shell
```

Stop if the checksum fails. The checksum detects a corrupted/mismatched download;
this pilot does not yet provide signed installers. Open a new Terminal window if
`netconverter` is not found, then verify:

```sh
netconverter --help
```

uv installs the command in an isolated tool environment; it does not require
installing the NetConverter engine. See [uv tools](https://docs.astral.sh/uv/guides/tools/).

## 3. Open your configuration folder

The folder you launch from is your workspace. For an initial synthetic demo:

```sh
mkdir -p ~/NetConverter-Demo
cd ~/NetConverter-Demo
curl --fail --location --output demo-asa.cfg https://raw.githubusercontent.com/valeronlabs/netconverter_terminals/v0.1.2/examples/demo-asa.cfg
wc -c demo-asa.cfg
netconverter
```

For your own staged file, instead `cd` to the folder already containing it.
Launching the client does not upload every file in that folder. **Selecting a file
with Open, Quick Convert, or Analyze only does upload that file to NetConverter.**

## 4. Complete connection setup

The first run asks for:

```text
Server URL [https://api.netconverter.ai/external/v1]:
NetConverter API key (hidden; paste here, then Enter; blank uses saved key):
Model provider: none / ollama / anthropic / openai / gemini [none]:
```

1. Press **Enter** to use the production API URL.
2. Paste your NetConverter terminal key at the hidden prompt. It will not echo.
3. Check the connected profile and remaining allowance.
4. Choose `none` for guided operation, or enter a provider, model ID, and provider
   key when prompted. Ollama uses the local service at `127.0.0.1:11434` and needs
   no provider API key.
5. A synthetic tool-call probe checks the selected model. If it fails, setup
   explains the error and offers **retry** or **guided**. It does not silently
   discard the failure. Inside the terminal, `/model` opens a masked-key form to
   test and reconnect without restarting or changing the server connection.

On macOS, credentials are stored in Keychain when available. Otherwise they remain
in memory for this session and must be entered again. Non-secret connection
preferences and resume metadata live in `.netconverter/` inside this folder.
Do not paste API keys into the conversational prompt, command arguments, issues,
or screenshots. The `login` command updates only the NetConverter connection;
`setup` lets you change both connections.

## 5. Submit an ASA migration

The layout adapts to 80×24; about 126 columns by 41 rows is comfortable. The
conversion form scrolls if necessary; Tab moves between controls.

1. Click `/open` or press **Ctrl+O**. The file browser lists names, byte sizes,
   and modification times. Select `demo-asa.cfg` with Enter or a click, and choose
   **Cisco ASA** as the source format. Files over 50,000 bytes are rejected.
2. Choose **Quick Convert** to upload that file and open conversion choices.
   **Open** uploads/selects without submitting a job; **Analyze only** uploads
   and submits analysis. Browsing alone does not upload anything.
3. Select the target: `palo_alto_set`, `palo_alto_xml`, or `palo_alto_panorama`.
4. Choose your target PAN-OS version, routing engine (`vr` or `lr`), and conversion
   mode from the live server choices. For an initial synthetic demo, use
   `like_for_like` and settings appropriate to your intended target.
5. For Panorama, enter the device group and template names.
6. Review cleanup. Expand **Advanced settings** for App-ID, security profiles,
   logging, explicit deny-all, profile group, and zone mappings. Unspecified optional overrides use the
   selected server mode's preset. See the [settings reference](docs/COMMANDS.md#conversion-settings).
7. Choose **Submit conversion**. Record the `trm_…` job ID shown in the terminal.

The terminal polls the server and displays its status. At completion it downloads
the available artifacts automatically. Warnings and validation failures matter:
read the reports before using an output. The client does not deploy to a firewall.

For a successful conversion, outputs can include:

```text
trm_….converted.set             # or converted.xml
trm_….mapping.yaml
trm_….report.txt
trm_….full-report.txt
trm_….evidence.txt
trm_….evidence.xlsx
trm_….evidence.json
trm_….pipeline-evidence.json
```

The job manifest determines actual names and available files. A failed validation
may provide evidence without a verified converted configuration. Files are saved
beside the source, with job-qualified names and verified hashes. Originals remain
untouched; a conflicting existing output is not overwritten. A download failure
can be retried with `/download` without another conversion.

HTTPS encrypts transport. Downloaded files are ordinary local files, **not** a
password-encrypted archive. Protect the folder according to your data policy.

## 6. Analyze and ask questions

With the ASA source selected, type `/analyze` (or choose **Analyze only** in the file browser). Wait for the server
job to complete, then try:

```text
/unused_objects
/routes
/policy
/flow {"source_ip":"192.0.2.10","destination_ip":"198.51.100.10","protocol":"tcp","destination_port":80}
/flow {"source_ip":"192.0.2.10","destination_ip":"198.51.100.10","protocol":"tcp","destination_port":81}
```

The sample ASA includes an explicit TCP-80 permit and an unused object. Treat the
returned coverage and unsupported cases as part of the answer. This is
configuration analysis, not a live firewall or packet-path test.

With a compatible model connected, you can instead type `Find unused objects` or
`Show routing recommendations`. For sensitive parameters, the terminal requests
structured input such as `/flow`; those values go directly to NetConverter.
The model selects an operation and does not receive detailed findings.

To inspect a generated target: `/resume trm_YOUR_JOB_ID`, `/target`, then
`/analyze`. Wait for analysis before `/unused_objects` or other questions.
To inspect an existing Palo Alto config: `/open`, select its vendor, upload,
and analyze it. Check the selected revision before each question.

## 7. Restart and resume

Press **Ctrl+Q** to leave the terminal. Return to the same folder and run
`netconverter` again. Resume an earlier job with `/resume JOB_ID`, or inspect
`/jobs`. A network interruption can leave a submission pending; `/resume` retries
that submission with the saved idempotency key.

Do not delete `.netconverter/` while recovering an interrupted submission.
In plain CLI mode, `netconverter resume JOB_ID` fetches status once; use
`netconverter download` after completion. The TUI handles polling and automatic
completion downloads.

## 8. Update or uninstall

To update, download and verify the new wheel, then run `uv tool install --force`
with that wheel path. Read its release notes first.

To remove the executable:

```sh
uv tool uninstall netconverter-terminal
```

This preserves configs, outputs, Keychain credentials, and per-folder state.
For a fresh onboarding reset, close the client, remove only this application's
entries under service **NetConverter Terminal** in Keychain Access, and remove
`.netconverter/` from the relevant workspace after you have finished recovery.
Do not delete the source configurations or downloaded evidence. Ask NetConverter
to revoke a server key if you no longer need its access; deleting a local copy
alone does not revoke it. This client never requires uninstalling Ollama or other
tools to reset its own setup.

See [troubleshooting](docs/COMMANDS.md#troubleshooting) if any step fails.
