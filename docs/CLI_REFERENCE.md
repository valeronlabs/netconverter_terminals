# CLI reference — netconverter 0.7.0

Generated from the command definitions by `scripts/gen_cli_reference.py`; do not edit by hand.
What the concepts mean (sign-in, exposure levels, the MCP bridge, guided migration, error codes):
[GUIDE.md](GUIDE.md). Settings, environment variables and bridge tools: [COMMANDS.md](COMMANDS.md).

Global options go **before** the command: `netconverter --workspace DIR --server URL COMMAND …`.

## Contents

- [`netconverter run`](#netconverter-run) — (advanced) open the full-screen app; the same as no command
- [`netconverter license`](#netconverter-license) — read and accept the client license
- [`netconverter walkthrough`](#netconverter-walkthrough) — a short guided tour of the client and its integrations
- [`netconverter login`](#netconverter-login) — store an API key, or sign in with --clerk
- [`netconverter logout`](#netconverter-logout) — remove the Clerk sign-in from the credential store
- [`netconverter whoami`](#netconverter-whoami) — show the signed-in account (never prints tokens)
- [`netconverter mcp`](#netconverter-mcp) — run the local stdio MCP server for AI clients
- [`netconverter connect`](#netconverter-connect) — wire an AI assistant (Claude, Cursor, Gemini, ChatGPT, …) to this folder
- [`netconverter update`](#netconverter-update) — upgrade from PyPI, or install the latest verified release from GitHub
- [`netconverter capabilities`](#netconverter-capabilities) — vendors, conversion paths and limits for your credential
- [`netconverter draft`](#netconverter-draft) — prepare and review a revisioned migration draft
  - [`netconverter draft catalog`](#netconverter-draft-catalog) — show design operations and qualification gaps
  - [`netconverter draft context`](#netconverter-draft-context) — show bounded interface facts and proposed mappings
  - [`netconverter draft prepare`](#netconverter-draft-prepare) — prepare a draft without executing a migration
  - [`netconverter draft decisions`](#netconverter-draft-decisions) — show the decisions of one draft revision
  - [`netconverter draft export`](#netconverter-draft-export) — save one draft revision's decisions document (YAML) in the workspace
  - [`netconverter draft import`](#netconverter-draft-import) — upload an edited decisions document as a new draft revision
  - [`netconverter draft propose`](#netconverter-draft-propose) — record typed operations or decision choices as a new revision
  - [`netconverter draft validate`](#netconverter-draft-validate) — check one draft revision; nothing is executed
  - [`netconverter draft review`](#netconverter-draft-review) — request the human review of one draft revision
  - [`netconverter draft execute`](#netconverter-draft-execute) — run a reviewed draft revision (needs --approval-ref)
  - [`netconverter draft job-status`](#netconverter-draft-job-status) — inspect a draft execution
  - [`netconverter draft download-result`](#netconverter-draft-download-result) — download one verified artifact from a draft execution
- [`netconverter project`](#netconverter-project) — prepare a candidate multi-device project; no project execution
  - [`netconverter project schema`](#netconverter-project-schema) — print the project document schema the server accepts
  - [`netconverter project get`](#netconverter-project-get) — show one project revision
  - [`netconverter project prepare`](#netconverter-project-prepare) — create a candidate project from prepared drafts and their links
  - [`netconverter project propose`](#netconverter-project-propose) — record a new project revision (devices and links)
- [`netconverter privacy`](#netconverter-privacy) — what your AI assistant may see from this folder's jobs (exposure level)
  - [`netconverter privacy status`](#netconverter-privacy-status) — show this folder's exposure level (the default action)
  - [`netconverter privacy level`](#netconverter-privacy-level) — set the level: none, masked, selected or full; raising asks for a typed confirmation
  - [`netconverter privacy apply`](#netconverter-privacy-apply) — keep an AI client's own file tools out of this folder
- [`netconverter setup`](#netconverter-setup) — first-run setup: connect to NetConverter and, optionally, a model
- [`netconverter jobs`](#netconverter-jobs) — list your NetConverter jobs
- [`netconverter resume`](#netconverter-resume) — follow a job (or finish an interrupted submission)
- [`netconverter validate`](#netconverter-validate) — check a configuration: readiness, findings, parse gaps
- [`netconverter analyze`](#netconverter-analyze) — (advanced) the same as validate
- [`netconverter optimize`](#netconverter-optimize) — cleanup and optimization findings for a configuration
- [`netconverter convert`](#netconverter-convert) — migrate a configuration to another vendor (--to)
- [`netconverter ask`](#netconverter-ask) — one plain-language question about the active job (needs --provider)
- [`netconverter query`](#netconverter-query) — a structured question about the active job (nat, routes, flow, …)
- [`netconverter download`](#netconverter-download) — save the active job's outputs beside its source, hash-verified
- [`netconverter allowance`](#netconverter-allowance) — your remaining allowance and limits (the same as capabilities)
- [`netconverter model-test`](#netconverter-model-test) — (advanced) check that --provider/--model can choose operations
- [`netconverter plain`](#netconverter-plain) — a line prompt instead of the full-screen app

## Global options

```
netconverter [-h] [--version] [--workspace DIR] [--server URL] [--provider NAME] [--model ID] COMMAND ...
```

| Argument / option | Meaning | Default |
| --- | --- | --- |
| `--version` | Print the client version and exit. |  |
| `--workspace` `DIR` | Configuration folder to work in (default: the current folder) |  |
| `--server` `URL` | NetConverter API URL (default: NETCONVERTER_URL, else production) |  |
| `--provider` `NAME` | Optional model provider for plain-language questions: openai, anthropic, gemini or ollama. Choices: `openai`, `anthropic`, `gemini`, `ollama`. |  |
| `--model` `ID` | Exact model ID for --provider (default: NETCONVERTER_MODEL) |  |

Examples:

```sh
netconverter                      # the full-screen app in this folder
netconverter --workspace ~/migrations jobs
netconverter --version
```

## <a id="netconverter-run"></a>`netconverter run`

(advanced) open the full-screen app; the same as no command.

```
netconverter run [-h]
```

No options besides `-h`/`--help`.

Example:

```sh
netconverter run
```

## <a id="netconverter-license"></a>`netconverter license`

Read and accept the client license.

```
netconverter license [-h] [--yes] [{show,accept,status}]
```

| Argument / option | Meaning | Default |
| --- | --- | --- |
| `license_action` (optional) | Show the full text, accept it, or print the acceptance status. Choices: `show`, `accept`, `status`. |  |
| `--yes` | Accept without a prompt (scripts) |  |

Examples:

```sh
netconverter license show
netconverter license accept
netconverter license status
```

## <a id="netconverter-walkthrough"></a>`netconverter walkthrough`

A short guided tour of the client and its integrations.

```
netconverter walkthrough [-h] [--all] [step]
```

| Argument / option | Meaning | Default |
| --- | --- | --- |
| `step` (optional) | Show one step (1-7) |  |
| `--all` | Print every step without pausing. |  |

Examples:

```sh
netconverter walkthrough
netconverter walkthrough 3
netconverter walkthrough --all
```

## <a id="netconverter-login"></a>`netconverter login`

Store an API key, or sign in with --clerk.

Two kinds of credential: **`--clerk`** signs you in with your NetConverter account (OAuth in the browser, or `--device` on a headless machine); without it, `login` stores an **API key** (`nck_…`) issued to you or your organisation. Either is kept in the OS keyring, or with `--store file` in a passphrase-encrypted file. See the [guide](GUIDE.md#sign-in-and-credentials).

```
netconverter login [-h] [--clerk | --key] [--device] [--store {auto,keyring,file}]
```

| Argument / option | Meaning | Default |
| --- | --- | --- |
| `--clerk` | Sign in with your NetConverter account (browser) |  |
| `--key` | Store an API key (the default) |  |
| `--device` | Clerk sign-in with a device code (headless machines) |  |
| `--store` `STORE` | Where to keep it: the OS keyring, or the passphrase-encrypted file (default auto: the keyring when available; NETCONVERTER_CREDENTIAL_STORE) Choices: `auto`, `keyring`, `file`. |  |

Examples:

```sh
netconverter login --clerk              # browser sign-in with your NetConverter account
netconverter login --clerk --device     # headless: shows a code to enter on another device
netconverter login                      # paste an API key (nck_…); stored, never echoed
netconverter login --clerk --store file # passphrase-encrypted file instead of the OS keyring
```

## <a id="netconverter-logout"></a>`netconverter logout`

Remove the Clerk sign-in from the credential store.

```
netconverter logout [-h] [--all]
```

| Argument / option | Meaning | Default |
| --- | --- | --- |
| `--all` | Also remove the stored API key for this server. |  |

Examples:

```sh
netconverter logout
netconverter logout --all
```

## <a id="netconverter-whoami"></a>`netconverter whoami`

Show the signed-in account (never prints tokens).

```
netconverter whoami [-h]
```

No options besides `-h`/`--help`.

Example:

```sh
netconverter whoami
```

## <a id="netconverter-mcp"></a>`netconverter mcp`

Run the local stdio MCP server for AI clients.

Started by an AI assistant, not by you: it speaks MCP over stdio. The assistant passes file **paths**; the bridge uploads the file itself. What the assistant may see is this folder's exposure level (`privacy`); `--level` can only lower it. See the [guide](GUIDE.md#ai-assistants-and-the-mcp-bridge).

```
netconverter mcp [-h] [--auth {auto,clerk,key}] [--mcp-url URL] [--no-remote] [--guided] [--level LEVEL] [--strict] [--full] [--no-upload-confirm] [--workspace WORKSPACE]
```

| Argument / option | Meaning | Default |
| --- | --- | --- |
| `--auth` `AUTH` | Credential: auto (the sign-in, else an API key), clerk or key; default from NETCONVERTER_MCP_AUTH, else NETCONVERTER_AUTH. Choices: `auto`, `clerk`, `key`. | `auto` |
| `--mcp-url` `URL` | NetConverter MCP endpoint for the remote tools (default: derived from --server) |  |
| `--no-remote` | Serve only the local file tools. |  |
| `--guided` | Revisioned draft tools with human approval; requires server capability. |  |
| `--level`, `--view` `LEVEL` | Lower this folder's exposure level for this process: none, masked, selected or full (strict = masked); never above `netconverter privacy level`; default from NETCONVERTER_MCP_VIEW. Choices: `none`, `masked`, `selected`, `full`, `strict`. |  |
| `--strict` | At most masked (the strict view) |  |
| `--full` | Up to full, when this folder's level is full (`netconverter privacy level full`; the guided-migration tools, prescan to submit_conversion, need it) |  |
| `--no-upload-confirm` | Never send a confirmation form before an upload or a queued conversion; the AI client's own tool approval confirms instead (for clients that decline forms unseen, e.g. ChatGPT, Claude Code; NETCONVERTER_MCP_UPLOAD_CONFIRM=0) |  |
| `--workspace` `WORKSPACE` | Folder the file tools may read and write. |  |

Examples:

```sh
netconverter mcp --workspace ~/migrations                 # what an AI assistant runs
netconverter mcp --workspace ~/migrations --level masked  # serve at most masked
netconverter mcp --workspace ~/migrations --auth key      # use the stored API key
netconverter mcp --workspace ~/migrations --no-upload-confirm
```

## <a id="netconverter-connect"></a>`netconverter connect`

Wire an AI assistant (Claude, Cursor, Gemini, ChatGPT, …) to this folder.

Writes the assistant's MCP settings so it starts `netconverter mcp` for this folder (`chatgpt` and `claude-ai` print hosted-connector steps instead).

```
netconverter connect [-h] [--all] [--print] [--yes] [--remove] [CLIENT]
```

| Argument / option | Meaning | Default |
| --- | --- | --- |
| `CLIENT` (optional) | Assistant to connect: claude-code, claude-desktop, cursor, vscode, codex, gemini, windsurf, devin, lmstudio, openclaw, chatgpt, claude-ai (omit to list them) Choices: `claude-code`, `claude-desktop`, `cursor`, `vscode`, `codex`, `gemini`, `windsurf`, `devin`, `lmstudio`, `openclaw`, `chatgpt`, `claude-ai`. |  |
| `--all` | Connect every AI assistant found on this computer. |  |
| `--print` | Show the change without applying it. |  |
| `--yes` | Apply without asking (scripts) |  |
| `--remove` | Remove the client's netconverter entry (openclaw) |  |

Examples:

```sh
netconverter connect                    # list assistants and their state
netconverter connect claude-code
netconverter connect codex              # also the ChatGPT desktop app's agent
netconverter connect chatgpt            # hosted-connector steps (and the desktop-agent pointer)
netconverter connect cursor --print     # show the change only
netconverter connect --all
```

## <a id="netconverter-update"></a>`netconverter update`

Upgrade from PyPI, or install the latest verified release from GitHub.

```
netconverter update [-h] [--check] [--yes] [--json]
```

| Argument / option | Meaning | Default |
| --- | --- | --- |
| `--check` | Only report whether a newer release exists. |  |
| `--yes` | Install without asking. |  |
| `--json` | With --check: print the result as JSON. |  |

Examples:

```sh
netconverter update --check
netconverter update
netconverter update --check --json
```

## <a id="netconverter-capabilities"></a>`netconverter capabilities`

Vendors, conversion paths and limits for your credential.

```
netconverter capabilities [-h]
```

No options besides `-h`/`--help`.

Example:

```sh
netconverter capabilities
```

## <a id="netconverter-draft"></a>`netconverter draft`

Prepare and review a revisioned migration draft.

Development preview of the revisioned draft contract ([guided-workflows.md](guided-workflows.md)); prints JSON.

```
netconverter draft [-h] {catalog,context,prepare,decisions,export,import,propose,validate,review,execute,job-status,download-result} ...
```

No options besides `-h`/`--help`.

Example:

```sh
netconverter draft catalog
```

### <a id="netconverter-draft-catalog"></a>`netconverter draft catalog`

Show design operations and qualification gaps.

```
netconverter draft catalog [-h]
```

No options besides `-h`/`--help`.

Example:

```sh
netconverter draft catalog
```

### <a id="netconverter-draft-context"></a>`netconverter draft context`

Show bounded interface facts and proposed mappings.

```
netconverter draft context [-h] --revision REVISION [--view-id {strict,interfaces}] [--offset OFFSET] [--limit LIMIT] draft_id
```

| Argument / option | Meaning | Default |
| --- | --- | --- |
| `draft_id` | Draft id returned by draft prepare. |  |
| `--revision` `REVISION` | **Required.** Draft revision to read (a positive integer) |  |
| `--view-id` `VIEW_ID` | Interfaces (names and proposed mappings) or strict (tokens only) Choices: `strict`, `interfaces`. | `interfaces` |
| `--offset` `OFFSET` | First item to return, for paging. |  |
| `--limit` `LIMIT` | Most items to return, for paging. |  |

Example:

```sh
netconverter draft context DRAFT_ID --revision 1 --view-id interfaces --limit 50
```

### <a id="netconverter-draft-prepare"></a>`netconverter draft prepare`

Prepare a draft without executing a migration.

```
netconverter draft prepare [-h] [--vendor SOURCE_VENDOR] [--to TARGET_VENDOR] [--workflow {studio,quick}] --idempotency-key IDEMPOTENCY_KEY path
```

| Argument / option | Meaning | Default |
| --- | --- | --- |
| `path` | Configuration file inside the workspace folder. |  |
| `--vendor` `SOURCE_VENDOR` | Source vendor code. | `cisco_asa` |
| `--to` `TARGET_VENDOR` | Target vendor code the server advertises for this credential. | `palo_alto_set` |
| `--workflow` `WORKFLOW` | Studio (review every decision) or quick (explicit defaults where they suffice) Choices: `studio`, `quick`. | `studio` |
| `--idempotency-key` `IDEMPOTENCY_KEY` | **Required.** Reuse this key when retrying the same request. |  |

Example:

```sh
netconverter draft prepare asa.cfg --vendor cisco_asa --to palo_alto_set --workflow studio --idempotency-key prepare-001
```

### <a id="netconverter-draft-decisions"></a>`netconverter draft decisions`

Show the decisions of one draft revision.

```
netconverter draft decisions [-h] --revision REVISION draft_id
```

| Argument / option | Meaning | Default |
| --- | --- | --- |
| `draft_id` | Draft id returned by draft prepare. |  |
| `--revision` `REVISION` | **Required.** Draft revision (a positive integer) |  |

Example:

```sh
netconverter draft decisions DRAFT_ID --revision 1
```

### <a id="netconverter-draft-export"></a>`netconverter draft export`

Save one draft revision's decisions document (YAML) in the workspace.

```
netconverter draft export [-h] --revision REVISION draft_id
```

| Argument / option | Meaning | Default |
| --- | --- | --- |
| `draft_id` | Draft id returned by draft prepare. |  |
| `--revision` `REVISION` | **Required.** Draft revision (a positive integer) |  |

Example:

```sh
netconverter draft export DRAFT_ID --revision 1
```

### <a id="netconverter-draft-import"></a>`netconverter draft import`

Upload an edited decisions document as a new draft revision.

```
netconverter draft import [-h] --revision REVISION --idempotency-key IDEMPOTENCY_KEY --yaml YAML_PATH draft_id
```

| Argument / option | Meaning | Default |
| --- | --- | --- |
| `draft_id` | Draft id returned by draft prepare. |  |
| `--revision` `REVISION` | **Required.** Draft revision (a positive integer) |  |
| `--idempotency-key` `IDEMPOTENCY_KEY` | **Required.** Any unique string; reuse it when retrying the same request. |  |
| `--yaml` `YAML_PATH` | **Required.** Local YAML path inside the workspace; uploaded directly. |  |

Example:

```sh
netconverter draft import DRAFT_ID --revision 1 --yaml DRAFT_ID.revision-1.yaml --idempotency-key import-001
```

### <a id="netconverter-draft-propose"></a>`netconverter draft propose`

Record typed operations or decision choices as a new revision.

```
netconverter draft propose [-h] --revision REVISION --idempotency-key IDEMPOTENCY_KEY --changes CHANGES draft_id
```

| Argument / option | Meaning | Default |
| --- | --- | --- |
| `draft_id` | Draft id returned by draft prepare. |  |
| `--revision` `REVISION` | **Required.** Draft revision (a positive integer) |  |
| `--idempotency-key` `IDEMPOTENCY_KEY` | **Required.** Any unique string; reuse it when retrying the same request. |  |
| `--changes` `CHANGES` | **Required.** JSON typed operations from draft catalog, or opaque decision choices. |  |

Example:

```sh
netconverter draft propose DRAFT_ID --revision 2 --changes '[...]' --idempotency-key propose-001
```

### <a id="netconverter-draft-validate"></a>`netconverter draft validate`

Check one draft revision; nothing is executed.

```
netconverter draft validate [-h] --revision REVISION --idempotency-key IDEMPOTENCY_KEY draft_id
```

| Argument / option | Meaning | Default |
| --- | --- | --- |
| `draft_id` | Draft id returned by draft prepare. |  |
| `--revision` `REVISION` | **Required.** Draft revision (a positive integer) |  |
| `--idempotency-key` `IDEMPOTENCY_KEY` | **Required.** Any unique string; reuse it when retrying the same request. |  |

Example:

```sh
netconverter draft validate DRAFT_ID --revision 2 --idempotency-key validate-001
```

### <a id="netconverter-draft-review"></a>`netconverter draft review`

Request the human review of one draft revision.

```
netconverter draft review [-h] --revision REVISION --idempotency-key IDEMPOTENCY_KEY draft_id
```

| Argument / option | Meaning | Default |
| --- | --- | --- |
| `draft_id` | Draft id returned by draft prepare. |  |
| `--revision` `REVISION` | **Required.** Draft revision (a positive integer) |  |
| `--idempotency-key` `IDEMPOTENCY_KEY` | **Required.** Any unique string; reuse it when retrying the same request. |  |

Example:

```sh
netconverter draft review DRAFT_ID --revision 2 --idempotency-key review-001
```

### <a id="netconverter-draft-execute"></a>`netconverter draft execute`

Run a reviewed draft revision (needs --approval-ref).

```
netconverter draft execute [-h] --revision REVISION --idempotency-key IDEMPOTENCY_KEY --approval-ref APPROVAL_REF draft_id
```

| Argument / option | Meaning | Default |
| --- | --- | --- |
| `draft_id` | Draft id returned by draft prepare. |  |
| `--revision` `REVISION` | **Required.** Draft revision (a positive integer) |  |
| `--idempotency-key` `IDEMPOTENCY_KEY` | **Required.** Any unique string; reuse it when retrying the same request. |  |
| `--approval-ref` `APPROVAL_REF` | **Required.** Reference issued after independent human review of this revision. |  |

Example:

```sh
netconverter draft execute DRAFT_ID --revision 2 --approval-ref APPROVAL_REF --idempotency-key execute-001
```

### <a id="netconverter-draft-job-status"></a>`netconverter draft job-status`

Inspect a draft execution.

```
netconverter draft job-status [-h] --draft-id DRAFT_ID --revision REVISION job_id
```

| Argument / option | Meaning | Default |
| --- | --- | --- |
| `job_id` | Job id returned by draft execute. |  |
| `--draft-id` `DRAFT_ID` | **Required.** The draft the job ran. |  |
| `--revision` `REVISION` | **Required.** The draft revision the job ran. |  |

Example:

```sh
netconverter draft job-status JOB_ID --draft-id DRAFT_ID --revision 2
```

### <a id="netconverter-draft-download-result"></a>`netconverter draft download-result`

Download one verified artifact from a draft execution.

```
netconverter draft download-result [-h] --draft-id DRAFT_ID --revision REVISION --artifact-id ARTIFACT_ID --manifest-revision MANIFEST_REVISION job_id
```

| Argument / option | Meaning | Default |
| --- | --- | --- |
| `job_id` | Job id returned by draft execute. |  |
| `--draft-id` `DRAFT_ID` | **Required.** The draft the job ran. |  |
| `--revision` `REVISION` | **Required.** The draft revision the job ran. |  |
| `--artifact-id` `ARTIFACT_ID` | **Required.** Artifact id from draft job-status. |  |
| `--manifest-revision` `MANIFEST_REVISION` | **Required.** Manifest revision from draft job-status. |  |

Example:

```sh
netconverter draft download-result JOB_ID --draft-id DRAFT_ID --revision 2 --artifact-id ARTIFACT_ID --manifest-revision 1
```

## <a id="netconverter-project"></a>`netconverter project`

Prepare a candidate multi-device project; no project execution.

Development preview: candidate multi-device projects built from drafts; no project execution.

```
netconverter project [-h] {schema,get,prepare,propose} ...
```

No options besides `-h`/`--help`.

Example:

```sh
netconverter project schema
```

### <a id="netconverter-project-schema"></a>`netconverter project schema`

Print the project document schema the server accepts.

```
netconverter project schema [-h]
```

No options besides `-h`/`--help`.

Example:

```sh
netconverter project schema
```

### <a id="netconverter-project-get"></a>`netconverter project get`

Show one project revision.

```
netconverter project get [-h] --revision REVISION project_id
```

| Argument / option | Meaning | Default |
| --- | --- | --- |
| `project_id` | Project id returned by project prepare. |  |
| `--revision` `REVISION` | **Required.** Project revision (a positive integer) |  |

Example:

```sh
netconverter project get PROJECT_ID --revision 1
```

### <a id="netconverter-project-prepare"></a>`netconverter project prepare`

Create a candidate project from prepared drafts and their links.

```
netconverter project prepare [-h] --devices DEVICES --links LINKS --idempotency-key IDEMPOTENCY_KEY
```

| Argument / option | Meaning | Default |
| --- | --- | --- |
| `--devices` `DEVICES` | **Required.** JSON array of device_id, draft_id and revision references. |  |
| `--links` `LINKS` | **Required.** JSON array of complete links and explicit expectations. |  |
| `--idempotency-key` `IDEMPOTENCY_KEY` | **Required.** Any unique string; reuse it when retrying the same request. |  |

Example:

```sh
netconverter project prepare --devices '[...]' --links '[...]' --idempotency-key project-001
```

### <a id="netconverter-project-propose"></a>`netconverter project propose`

Record a new project revision (devices and links).

```
netconverter project propose [-h] --expected-revision EXPECTED_REVISION --devices DEVICES --links LINKS --idempotency-key IDEMPOTENCY_KEY project_id
```

| Argument / option | Meaning | Default |
| --- | --- | --- |
| `project_id` | Project id returned by project prepare. |  |
| `--expected-revision` `EXPECTED_REVISION` | **Required.** The revision you are changing; refused if the project moved on. |  |
| `--devices` `DEVICES` | **Required.** JSON array of device_id, draft_id and revision references. |  |
| `--links` `LINKS` | **Required.** JSON array of complete links and explicit expectations. |  |
| `--idempotency-key` `IDEMPOTENCY_KEY` | **Required.** Any unique string; reuse it when retrying the same request. |  |

Example:

```sh
netconverter project propose PROJECT_ID --expected-revision 1 --devices '[...]' --links '[...]' --idempotency-key project-002
```

## <a id="netconverter-privacy"></a>`netconverter privacy`

What your AI assistant may see from this folder's jobs (exposure level).

The **exposure level** decides what an AI assistant sees from this folder's jobs. See the [guide](GUIDE.md#privacy-and-exposure-levels).

```
netconverter privacy [-h] ACTION ...
```

No options besides `-h`/`--help`.

Example:

```sh
netconverter privacy
```

### <a id="netconverter-privacy-status"></a>`netconverter privacy status`

Show this folder's exposure level (the default action).

```
netconverter privacy status [-h] [--json]
```

| Argument / option | Meaning | Default |
| --- | --- | --- |
| `--json` | Print the status as JSON. |  |

Examples:

```sh
netconverter privacy status
netconverter privacy status --json
```

### <a id="netconverter-privacy-level"></a>`netconverter privacy level`

Set the level: none, masked, selected or full; raising asks for a typed confirmation.

Raising a level asks you to type a phrase in a terminal, so no assistant can raise it; every change is recorded in `.netconverter/privacy-audit.jsonl`.

```
netconverter privacy level [-h] [--sections LIST] LEVEL
```

| Argument / option | Meaning | Default |
| --- | --- | --- |
| `LEVEL` | None, masked, selected or full. Choices: `none`, `masked`, `selected`, `full`. |  |
| `--sections` `LIST` | With selected: comma-separated sections: interfaces, routes, policy, nat, vpn, objects, management, translation, unparsed_lines, target, reports. |  |

Examples:

```sh
netconverter privacy level full       # asks you to type "raise to full"
netconverter privacy level masked     # lowering needs no confirmation
netconverter privacy level selected --sections nat,routes
```

### <a id="netconverter-privacy-apply"></a>`netconverter privacy apply`

Keep an AI client's own file tools out of this folder.

```
netconverter privacy apply [-h] --client CLIENT [--print] [--yes]
```

| Argument / option | Meaning | Default |
| --- | --- | --- |
| `--client` `CLIENT` | **Required.** Assistant to configure: claude-code, cursor, gemini, codex, openclaw. Choices: `claude-code`, `cursor`, `gemini`, `codex`, `openclaw`. |  |
| `--print` | Show the change without applying it. |  |
| `--yes` | Apply without asking (scripts) |  |

Examples:

```sh
netconverter privacy apply --client claude-code
netconverter privacy apply --client codex --print
```

## <a id="netconverter-setup"></a>`netconverter setup`

First-run setup: connect to NetConverter and, optionally, a model.

```
netconverter setup [-h]
```

No options besides `-h`/`--help`.

Example:

```sh
netconverter setup
```

## <a id="netconverter-jobs"></a>`netconverter jobs`

List your NetConverter jobs.

```
netconverter jobs [-h]
```

No options besides `-h`/`--help`.

Example:

```sh
netconverter jobs
```

## <a id="netconverter-resume"></a>`netconverter resume`

Follow a job (or finish an interrupted submission).

```
netconverter resume [-h] [--json] [--all] [job_id]
```

| Argument / option | Meaning | Default |
| --- | --- | --- |
| `job_id` (optional) | Job to follow (default: the folder's active job) |  |
| `--json` | Print the raw API response (JSON) |  |
| `--all` | List every finding, not only the first few. |  |

Examples:

```sh
netconverter resume
netconverter resume tra_0123456789ab --all
```

## <a id="netconverter-validate"></a>`netconverter validate`

Check a configuration: readiness, findings, parse gaps.

```
netconverter validate [-h] [--vendor CODE] [--options JSON] [--json] [--all] file
```

| Argument / option | Meaning | Default |
| --- | --- | --- |
| `file` | Configuration file inside the workspace folder. |  |
| `--vendor` `CODE` | Source vendor code, e.g. fortinet or cisco_asa (`netconverter capabilities` lists them) |  |
| `--options` `JSON` | Job settings as a JSON object, for example '{"panos_target_version":"12.1"}'; a YAML v2 decisions file goes in as {"yaml_v2": "<YAML text>"} (convert only) | `{}` |
| `--json` | Print the raw API response (JSON) |  |
| `--all` | List every finding, not only the first few. |  |

Examples:

```sh
netconverter validate edge-fw.cfg --vendor cisco_asa
netconverter validate edge-fw.cfg --vendor fortinet --json
```

## <a id="netconverter-analyze"></a>`netconverter analyze`

(advanced) the same as validate.

```
netconverter analyze [-h] [--vendor CODE] [--options JSON] [--json] [--all] file
```

| Argument / option | Meaning | Default |
| --- | --- | --- |
| `file` | Configuration file inside the workspace folder. |  |
| `--vendor` `CODE` | Source vendor code, e.g. fortinet or cisco_asa (`netconverter capabilities` lists them) |  |
| `--options` `JSON` | Job settings as a JSON object, for example '{"panos_target_version":"12.1"}'; a YAML v2 decisions file goes in as {"yaml_v2": "<YAML text>"} (convert only) | `{}` |
| `--json` | Print the raw API response (JSON) |  |
| `--all` | List every finding, not only the first few. |  |

Example:

```sh
netconverter analyze edge-fw.cfg --vendor cisco_asa
```

## <a id="netconverter-optimize"></a>`netconverter optimize`

Cleanup and optimization findings for a configuration.

```
netconverter optimize [-h] [--vendor CODE] [--options JSON] [--json] [--all] file
```

| Argument / option | Meaning | Default |
| --- | --- | --- |
| `file` | Configuration file inside the workspace folder. |  |
| `--vendor` `CODE` | Source vendor code, e.g. fortinet or cisco_asa (`netconverter capabilities` lists them) |  |
| `--options` `JSON` | Job settings as a JSON object, for example '{"panos_target_version":"12.1"}'; a YAML v2 decisions file goes in as {"yaml_v2": "<YAML text>"} (convert only) | `{}` |
| `--json` | Print the raw API response (JSON) |  |
| `--all` | List every finding, not only the first few. |  |

Example:

```sh
netconverter optimize edge-fw.cfg --vendor palo_alto_xml
```

## <a id="netconverter-convert"></a>`netconverter convert`

Migrate a configuration to another vendor (--to).

Uploads the file and converts it in one step. For a guided migration (prescan, then your decisions, then the conversion) use an AI assistant with the bridge ([guide](GUIDE.md#guided-migration-prescan-decisions-conversion)), or Quick Convert / Conversion Studio in the portal.

```
netconverter convert [-h] [--vendor CODE] [--to CODE] [--options JSON] [--json] [--all] file
```

| Argument / option | Meaning | Default |
| --- | --- | --- |
| `file` | Configuration file inside the workspace folder. |  |
| `--vendor` `CODE` | Source vendor code, e.g. fortinet or cisco_asa (`netconverter capabilities` lists them) |  |
| `--to` `CODE` | Target vendor code, e.g. palo_alto_xml. |  |
| `--options` `JSON` | Job settings as a JSON object, for example '{"panos_target_version":"12.1"}'; a YAML v2 decisions file goes in as {"yaml_v2": "<YAML text>"} (convert only) | `{}` |
| `--json` | Print the raw API response (JSON) |  |
| `--all` | List every finding, not only the first few. |  |

Examples:

```sh
netconverter convert edge-fw.cfg --vendor cisco_asa --to palo_alto_xml
netconverter convert edge-fw.cfg --vendor cisco_asa --to palo_alto_set --options '{"panos_target_version":"11.2"}'
```

## <a id="netconverter-ask"></a>`netconverter ask`

One plain-language question about the active job (needs --provider).

```
netconverter ask [-h] question
```

| Argument / option | Meaning | Default |
| --- | --- | --- |
| `question` | The question, in quotes. |  |

Example:

```sh
netconverter --provider anthropic ask "Which rules allow tcp/22 from outside?"
```

## <a id="netconverter-query"></a>`netconverter query`

A structured question about the active job (nat, routes, flow, …).

```
netconverter query [-h] [--arguments JSON] operation
```

| Argument / option | Meaning | Default |
| --- | --- | --- |
| `operation` | Unused_objects, unparsed_lines, routes, interfaces, policy, nat, dependencies or flow. |  |
| `--arguments` `JSON` | Parameters as a JSON object, e.g. '{"object_name":"NAME"}' for dependencies. | `{}` |

Examples:

```sh
netconverter query nat
netconverter query dependencies --arguments '{"object_name":"WEB-SRV"}'
```

## <a id="netconverter-download"></a>`netconverter download`

Save the active job's outputs beside its source, hash-verified.

```
netconverter download [-h]
```

No options besides `-h`/`--help`.

Example:

```sh
netconverter download
```

## <a id="netconverter-allowance"></a>`netconverter allowance`

Your remaining allowance and limits (the same as capabilities).

```
netconverter allowance [-h]
```

No options besides `-h`/`--help`.

Example:

```sh
netconverter allowance
```

## <a id="netconverter-model-test"></a>`netconverter model-test`

(advanced) check that --provider/--model can choose operations.

```
netconverter model-test [-h]
```

No options besides `-h`/`--help`.

Example:

```sh
netconverter --provider ollama --model qwen2.5 model-test
```

## <a id="netconverter-plain"></a>`netconverter plain`

A line prompt instead of the full-screen app.

```
netconverter plain [-h] [instruction]
```

| Argument / option | Meaning | Default |
| --- | --- | --- |
| `instruction` (optional) | Run one app command (e.g. '/jobs') and exit. |  |

Examples:

```sh
netconverter plain
netconverter plain '/jobs'
```
