# Changelog

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
