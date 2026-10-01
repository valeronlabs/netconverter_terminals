# Changelog

## 0.1.5 — 2026-10-01

- Display server-authorized unlimited allowances as Unlimited in the status line
  and `/allowance`. This client update does not grant or change server entitlements.

## 0.1.4 — 2026-10-01

- Skip `evidence.json` and `pipeline-evidence.json` in automatic downloads and
  `/download`. Keep converted configs, YAML, reports and TXT/XLSX evidence.
- Existing local artifacts are not deleted. Follow-up query JSON/TXT is unchanged.

## 0.1.3 — 2026-10-01

- Replace modal forms, dropdowns and oversized buttons with compact inline
  keyboard questions: arrow keys choose, Enter continues, Esc cancels a choice.
- Disable mouse capture so normal terminal text selection works.
- `/convert` starts with an ASA source, then asks separately for Palo Alto output,
  server-supported options, cleanup and optional advanced overrides. Show the
  review before explicit job submission; uploads are separately confirmed.
- `/open`, `/analyze` and `/model` use the same inline flow. Keep keys masked and
  out of conversation history, preserve model connections on failed retries.
- A selected Palo Alto source now leads `/convert` to ASA file selection instead
  of leaving the user at a source-format validation error.
- Preserve server job status, warnings, downloads, privacy and no-clobber behavior.

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
