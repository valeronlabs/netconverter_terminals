# Agent guidance

This is the public NetConverter terminal client, licensed under MIT. It does not
contain the hosted conversion engine. Read README.md, CONTRIBUTING.md, and
`docs/PRIVACY.md` before changing behavior.

- Preserve the restricted model operation interface, workspace boundary, explicit
  conversion choices, credential-store policy, retry semantics, and output hashes.
- Use synthetic fixtures only. Never add keys, private infrastructure details,
  customer configurations, workspace state, or generated customer reports.
- Run `uv sync --frozen --group dev`, `uv run pytest tests -q`, and a wheel build
  for a release. Keep customer documentation aligned with actual CLI behavior.
- Do not claim backend privacy acceptance, platform support, or model compatibility
  beyond the recorded evidence in `docs/VERIFICATION.md`.
- Do not change or deploy the hosted service as an implied part of a client edit.
