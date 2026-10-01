# Pilot verification status

Recorded for the initial public client release, October 1, 2026.

## Client checks

The automated suite includes HTTP protocol mocks for all four model adapters,
Textual interaction tests, hidden-key setup, the production URL default,
workspace and byte boundaries, canary-based model-payload checks, forbidden
operations, retry idempotency, restart/resume, revision selection, and preservation
of originals and existing outputs. Run it using [CONTRIBUTING.md](../CONTRIBUTING.md).
These are client tests; mock responses do not prove a live provider/model works.

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
