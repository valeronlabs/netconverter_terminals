# Pilot verification status

Updated for client 0.1.2, October 1, 2026.

## Client checks

The automated suite includes HTTP protocol mocks for all four model adapters,
Textual interaction tests, hidden-key setup, the production URL default,
workspace and byte boundaries, canary-based model-payload checks, forbidden
operations, retry idempotency, restart/resume, revision selection, and preservation
of originals and existing outputs. Run it using [CONTRIBUTING.md](../CONTRIBUTING.md).
These are client tests; mock responses do not prove a live provider/model works.

## 0.1.2 interface and setup checks

The automated suite has 42 passing cases, including the approved welcome layout
at 126×41 and 80×24, readable help, file-browser upload boundaries, ASA-only Quick
Convert, oversized inputs, explicit conversion decisions, model retry preserving
a working connection, and failed-download retry. Synthetic screenshots of the
actual Textual application were inspected at both sizes. No customer files or keys
were used in screenshots or public tests. The design's example logs, ETA, archive
encryption, cancellation and fabricated outputs are not product capabilities.

The original customer OpenAI failure was not diagnosed from the old generic error.
The release adds actionable safe errors and retry; live hosted-model acceptance
remains open. No server code or conversion algorithm changes are included. The updated client
also passed a read-only production HTTPS capabilities/job-list check using the
existing terminal profile. This check submitted no jobs and used no allowance.

## Service workflow evidence

Before public packaging, a real production HTTPS migration submitted a synthetic
ASA configuration of **exactly 50,000 bytes**, returned a `trm_` job ID, completed
with warnings, and downloaded eight hash-verified artifacts. Time from upload to
initial artifact download was **156.278 seconds** for that one run. The YAML parsed,
and the evidence workbook contained 23 sheets. Restart/resume and identical
repeat downloads were checked; the source hash did not change.

A 50,001-byte input was rejected before a job allowance was consumed. Restricted
API access and the read-only MCP catalog were checked. Staging exercises covered
SET, XML, and Panorama outputs. The recorded production run covered SET; it does
not constitute production acceptance of every format and option combination.

These measurements are evidence for specific synthetic cases, not a runtime SLA
or evidence that every 50 KB configuration finishes equally quickly. Validation
is not bypassed to meet a demo time target.

## Remaining acceptance

- Complete backend AI-provider payload privacy audit; the public pilot starts with
  synthetic configurations.
- Record each customer's actual hosted provider/model compatibility. A local
  Ollama model was exercised previously; hosted adapter tests are protocol mocks.
- Windows customer installation and workflow acceptance. Do not infer Windows
  support from a platform-independent wheel.
- Broader production combinations of output format, PAN-OS version, routing mode,
  App-ID, cleanup, policy, and unsupported configuration features.
- Public self-service enrollment, signed installers, and broader distribution.

Warnings, unsupported cases, and report-only findings remain visible. Inspect
reports and validate a generated configuration for its intended environment
before deployment. The client never pushes it to a firewall automatically.
