# Guided draft client contract — development preview

This is an opt-in client implementation for a **proposed** server contract. It is
not a claim that production supports drafts, independent approval or these routes.
Existing conversion commands and ordinary MCP remain unchanged. Missing support
returns `unsupported_capability` before reading or uploading configuration files.

The first client slice supports ASA to Palo Alto SET. It supplies CLI/MCP adapters,
bounded projected data, local YAML transfer, job status and verified artifact
downloads. The server must implement
and qualify persistence, per-user isolation, decisions, validation, human review,
restricted credentials and execution enforcement before enabling this contract.

Approval has one scope: `migration_submission`. It authorizes running the approved
revision through the conversion pipeline. Preparation can remain `not_evaluated`
or `needs_review` while submission readiness is `ready_for_submission`; neither
the approval nor a completed job means the generated configuration is safe to
deploy. The separate engine verdict, coverage, gaps and device validation remain
visible. Known parse failures block this initial submission path.

## CLI walkthrough

Sign in beforehand using existing `netconverter login` or `login --clerk`. These
commands print structured JSON, do not prompt for credentials and do not initialize
a model provider. All paths are inside the explicit workspace.

```sh
netconverter --workspace ~/migrations draft prepare asa.cfg \
  --vendor cisco_asa --to palo_alto_set --workflow studio \
  --idempotency-key prepare-20261024-001
netconverter --workspace ~/migrations draft decisions DRAFT_ID --revision 1
netconverter --workspace ~/migrations draft export DRAFT_ID --revision 1
# Edit the downloaded YAML locally, then import its path:
netconverter --workspace ~/migrations draft import DRAFT_ID --revision 1 \
  --yaml DRAFT_ID.revision-1.yaml --idempotency-key import-20261024-001
# Use the new revision returned by import:
netconverter --workspace ~/migrations draft validate DRAFT_ID --revision 2 \
  --idempotency-key validate-20261024-001
netconverter --workspace ~/migrations draft review DRAFT_ID --revision 2 \
  --idempotency-key review-20261024-001
# Complete independent human review in the returned trusted server page first:
netconverter --workspace ~/migrations draft execute DRAFT_ID --revision 2 \
  --approval-ref APPROVAL_REF --idempotency-key execute-20261024-001
netconverter --workspace ~/migrations draft job-status JOB_ID \
  --draft-id DRAFT_ID --revision 2
# Use the artifact ID and manifest revision from the completed job's status:
netconverter --workspace ~/migrations draft download-result JOB_ID \
  --draft-id DRAFT_ID --revision 2 --artifact-id ARTIFACT_ID --manifest-revision 1
```

Use `--workflow quick` when explicit defaults suffice. Both paths still require
server validation and independent human approval in this new contract. Reuse an
idempotency key only for the same logical request and bytes. After changing input
or reconciling a revision conflict, use a new key. The server must reject a reused
key with a different payload; the client does not persist an implicit active draft.

If execution commits but its response is lost, repeat the same execution command
with the same approval reference and idempotency key. A consumed receipt recovers
its original job from the immutable execution binding; it cannot create another
conversion. Revalidation or later edits do not rewrite that earlier job. Recovery
still checks current authorization, the receipt identity, its submission scope
and matching approved content hashes. An unconsumed receipt requires current
validation and submission readiness before a new job can be created.

`draft catalog` retrieves the versioned server operation catalog. Development
preview typed batches support interface remapping, zone mapping, source scope and
explicit policy options through the existing server YAML compiler. The client
requires the server catalog to match its generated schema before sending a typed
batch. All entries remain awaiting qualification; routing redesign and switching
operations are planned and refused. Existing minted decision/choice schemas remain
available for compatible callers. YAML imports are proposals and never approvals.
The client does not parse or rewrite YAML.

```sh
netconverter draft catalog
netconverter draft context DRAFT_ID --revision 1 --view-id interfaces --limit 50
netconverter draft propose DRAFT_ID --revision 1 --idempotency-key remap-001 \
  --changes '[{"operation":"interface.remap","parameters":{"source":"Gi0/1","target":"ethernet1/4"}}]'
```

The server resolves source aliases and rejects conflicting destination assignments.
Every batch applies atomically. `revision_conflict` and `idempotency_conflict` are
distinct errors. Regenerate `guided_operations.json` using the server repository's
`scripts/export_guided_catalog.py --output <terminal>/src/netconverter_cli/guided_operations.json`;
use `--check` to verify parity. Do not hand-maintain a second schema.

The `interfaces` context returns selected observed names, addresses and zones beside
desired mappings. It excludes descriptions, credentials and raw configuration;
source fields are untrusted data. Continue with `--offset` from `next_offset`.
The `strict` context remains a summary. Decision requirements distinguish advisory
source-scope/context questions from invalidated dependencies that block submission.
Their completeness flag remains false; an empty list is not migration qualification.

## MCP surface

Run `netconverter mcp --workspace ~/migrations --guided`. Connection setup does not
silently opt existing assistants into this mode. The mode exposes `account`, the
following authorized tools in fixed order:

0. `get_design_catalog`
1. `prepare_draft`
2. `get_required_decisions`
3. `read_context`
3. `propose_changes`
4. `validate_draft`
5. `request_review`
6. `execute_approved`
7. `job_status`
8. `wait_for_job`
9. `download`

Catalog and draft task tools stay first. Job tools require `get_job_status` capability;
`download` exposes only the supported YAML/artifact argument forms. Generated
artifacts require explicit job, draft, revision, artifact and manifest identities.
No single-job legacy download is available in guided mode. `wait_for_job` rechecks
capabilities and provenance on every poll, with a default 30-second polling budget
(maximum 45; zero requests one snapshot). Each request receives the remaining
timeout budget. This is not a hard wall-clock guarantee: network inactivity timeouts
and credential refresh can overrun it. Calls return the last observed status with
`waited_s` and `timed_out`, or a safe domain error if authorization or transport fails.

`submit_file` is hidden and refused even if called by name. There is no approval
tool, legacy submission fallback or general upstream MCP proxy in guided mode.
The server must also deny legacy execution using this restricted credential;
client tool filtering is not that authorization boundary.

Resources use revision-qualified draft context, evidence digest and catalog entry
URIs. They return the same projected domain envelope as tools, encoded as JSON.
Every read checks current capability; no client resource cache is implemented.
Static `migration-studio` and `pre-cutover-review` prompts provide guidance without
granting approval. Host support determines resource attachment and slash-command
naming. The existing protocol versions remain; no new TTL extension is advertised.
Tool schemas conform to the [MCP 2025-11-25 tools contract](https://modelcontextprotocol.io/specification/2025-11-25/server/tools).

## Required server capability

All requests use the existing authenticated External API transport, no redirects
and `X-NetConverter-View: strict`. Guided responses use identity encoding; JSON
metadata/error bodies are streamed with a 2,000,000-byte limit before parsing.
`GET /capabilities` must return its existing
`success/data` envelope with the following object under `data.guided_workflows`:

```json
{
  "contract_version": "1",
  "enabled": true,
  "approval_mode": "human_bound",
  "agent_restricted": true,
  "view_mode": "strict",
  "view_enforced_by": "server",
  "migration_pairs": [{"source_vendor": "cisco_asa", "target_vendor": "palo_alto_set"}],
  "operations": ["get_design_catalog", "prepare_draft", "get_required_decisions", "propose_changes",
    "validate_draft", "request_review", "execute_approved", "export_document",
    "read_context", "read_evidence", "read_catalog", "get_job_status", "download_artifact"]
}
```

Only authorized operations are listed; capability is fetched again before every
action. Unknown contract versions, absent strict enforcement or absent agent
restriction refuse. The server must derive these assertions from the authenticated
principal and current policy, never from model arguments.

## Proposed REST contract

Paths below are relative to `/external/v1`; all are authenticated and owner-scoped.
The terminal contract tests use synthetic HTTP fixtures. Separate server tests
qualify persistence and the assembled path; neither proves live deployment.
No endpoint may authorize by a caller-supplied tenant or owner.

| Action | Method/path | Request/response requirements |
| --- | --- | --- |
| Prepare | `POST /drafts` | Direct UTF-8 source, SHA-256, migration kind, fixed pair, quick/studio; return matching source hash, draft identity, revision and content hash. |
| Read/decisions | `GET /drafts/{id}?revision=n` | Exact immutable revision, migration kind, source/target, content hash and typed decision choices. Used before resumed mutations/export. |
| Import/propose | `POST /drafts/{id}/proposals` | `expected_revision`; either direct document plus SHA-256 or opaque choices; return same draft with strictly newer revision. |
| Validate | `POST /drafts/{id}/validate` | `expected_revision`; return validation against that exact revision. |
| Review | `POST /drafts/{id}/review-requests` | `expected_revision`; return review ID and exact same-origin `/drafts/{id}/reviews/{review_id}` URL, with no query token/fragment. |
| Approval status | `GET /drafts/{id}/approval-status?revision=n&approval_ref=...` | Exact draft/revision/reference, human-bound and `approval_scope=migration_submission`. An approved receipt requires `submission_readiness=ready_for_submission` and equal current/validated content hashes. A consumed receipt returns the immutable prior execution binding for recovery, even when a newer validation blocks another run. |
| Execute | `POST /guided/jobs` | Only `approved_draft_id`, `draft_revision`, `approval_ref`; server atomically checks ownership, receipt identity/content and idempotency. Before creating a job it also checks current policy/validation, readiness, approval freshness and active approving session. A consumed receipt can only return its original job. |
| YAML export | `GET /drafts/{id}/document?revision=n` | Exact draft/revision plus UTF-8 `document` and authenticated `sha256`; bytes never returned to MCP. |
| Job status | `GET /guided/jobs/{id}` | First read the explicit draft revision. Require matching job/draft/revision, migration kind, vendor pair and content hash; return a typed status and optional integer progress. |
| Artifact manifest | `GET /guided/jobs/{id}/artifacts?manifest_revision=n` | Require a completed job advertising this manifest revision, repeat the same provenance and artifact descriptor, and verify exact agreement before fetching bytes. |
| Artifact bytes | `GET /guided/jobs/{id}/artifacts/{artifact_id}?manifest_revision=n` | Authenticated fixed route, no redirects; bounded stream with exact byte length and SHA-256 before local publication. |
| Context | `GET /drafts/{id}/context?revision=n&view_id=...` | Exact revision and view identity; allowlisted fields only. |
| Evidence | `GET /guided/jobs/{id}/evidence-digest?digest_revision=n` | Exact job and digest revision; projected verdict/coverage. |
| Catalog | `GET /catalog/{version}/entries/{entry_id}` | Exact catalog version and entry identity; no configuration-derived prose. |

Writes require a caller-supplied `Idempotency-Key` matching `[A-Za-z0-9_-]{8,128}`.
Auth refresh retains the original body/key; revision conflicts are not retried or
merged automatically. Unknown server error prose is replaced with fixed safe codes
and messages. No aggregate tenant counts or credential strings enter errors.

Guided jobs use `/guided/jobs` for submission, status, evidence and downloads.
The client refuses the ordinary `/jobs` and `/quick/jobs` paths in this mode.
The restricted server credential must enforce that boundary independently.
Human verification uses the trusted review page and its separate portal session;
there is no bridge tool that records or fabricates approval.

Job states are `queued`, `running`, `complete`, `failed` and `stale`. A completed
job may provide `manifest_revision` and up to ten `artifacts`; both fields must occur
together. An artifact descriptor contains only a server-minted `art_` plus 32
lowercase hex characters, `kind` (`target_config`, `evidence_report` or
`evidence_workbook`), `sha256` and a positive `bytes` length up to 32 MiB. IDs must be
unique. Missing artifacts are unavailable, never inferred from filenames.

Artifact manifests repeat `job_id`, `draft_id`, `revision`, `draft_kind`,
`source_vendor`, `target_vendor`, `content_sha256`, `manifest_revision` and
`artifacts`. Server filenames, URLs, raw output and arbitrary messages are excluded.
The local name is computed as `JOB_ID.ARTIFACT_ID.set`, `.json` or `.xlsx` according
to kind. Only the local receipt and verified descriptor reach the assistant; file
contents stay on disk. There is no archive extraction or overwrite option.

## Disclosure and file safety

The machine-readable output schema lives in `drafts.OUTPUT_SCHEMA`. Unknown fields
are omitted; malformed recognized fields fail instead of hiding required decisions.
Opaque references are server-minted (`dec_`, `cho_`, `ent_` plus 32 lowercase hex
characters), checked against the server's draft/catalog membership. They must never
be copied from source names. Other resource IDs are server-minted, not source text.
Names, comments, descriptions, source lines, arbitrary labels, YAML and credentials
do not belong in projected fields. These rules require server qualification too.

New file access uses POSIX no-follow directory descriptors or, in the Windows
candidate, held Windows handles on local NTFS volumes, rejecting reparse points.
Reads are bounded (source up to 50,000 bytes; decision YAML up to 1,000,000 bytes).
Source replacement/change is refused; exports verify revision/digest and use
atomic no-clobber publication. Generated artifacts also bind the job and manifest,
check size before accumulation, refuse compressed responses and verify the final
checksum. Any guided endpoint's 401 body is closed without reading before at most
one credential refresh; retries preserve the request body and idempotency key.
Existing edited files are preserved. The Windows candidate uses a protected
owner-rights DACL for newly published files and refuses unsupported volumes.
Use a workspace that is writable only by trusted users. Windows guided transfers
reject files with multiple hard links and check again after a snapshot read, but
cannot establish a file's history or detect every transient link change. These
checks do not protect a workspace controlled by a malicious local user.
Windows security review and client qualification remain pending; ordinary client
file behavior is unchanged.

## Explicit remaining work

- Server contract, auth #836, isolated staging and real-client end-to-end proof.
- Catalog semantics, rich conversational edits/selective disclosure, and explicit
  partial coverage acceptance. Submission readiness is separate from the generated output verdict; known parse failures block the initial path.
- Windows secure file IO and acceptance; bounded private resource cache if warranted.
- Browser/TUI continuity, built-in AI, optimization/validation draft types and more vendors.
- Package version/release and public distribution approval. This development slice
  neither upgrades the installed terminal nor changes production.


## Candidate multi-device projects (development preview)

`netconverter project schema`, `prepare`, `get`, and `propose` use the server's
`project_2` contract. Guided MCP offers `get_project_schema`, `prepare_project`,
`get_project`, and `propose_project` only when freshly advertised for the credential.
Project access needs the server's separate project opt-in and schema qualification;
this client does not enable them. Existing servers and single-device callers keep
their current tools.

Prepare devices using the supported guided draft workflow first. Supply bounded
`devices` JSON references (`device_id`, `draft_id`, `revision`) and complete `links`
JSON. Each link has two target-interface endpoints and explicit optional booleans
`same_subnet`, `same_vlan_tag`, and `ospf_adjacency`. Missing expectations remain
questions. Setting an expectation does not configure routing or switch features.

```
netconverter project schema
netconverter project get project_<server-issued-id> --revision 1
```

`prepare` requires `--devices`, `--links`, and `--idempotency-key`; `propose` also
requires the project ID and `--expected-revision`. Proposals replace the complete
membership/topology atomically. Reuse the identical payload/key after an uncertain
write; reconcile revision and idempotency conflicts separately. Read a new device
revision explicitly before refreshing a stale project.

The schemas are generated by the server's `scripts/export_guided_catalog.py --project`.
Client mutation requires an exact schema match; bounded response projection verifies
project/revision identity, canonical snapshot hash and evidence binding. Raw configs,
YAML, arbitrary server prose and approval fields never enter this project view.
Only source-fact link comparisons under proposed mappings are reported. Compiled
target preservation, runtime/lab checks, project approval and execution remain
unavailable. Do not substitute individual executions for aggregate project approval.

Synthetic MCP → REST → PostgreSQL proof covers frozen revisions, conflicting prefixes,
retry/conflict handling, owner isolation, stale dependencies and flag revocation.
This is not two real desktop-client acceptance, deployed service proof, Windows
transfer qualification or a public package release.
