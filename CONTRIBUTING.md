# Development

This repository contains the independently packaged Python terminal client.
Server implementation and credentials do not belong here.

```sh
git clone https://github.com/valeronlabs/netconverter_terminals.git
cd netconverter_terminals
uv sync --frozen --group dev
uv run pytest tests -q
uv run python -m build --wheel
uv run netconverter --help
```

Use Python 3.12 or newer. Tests use synthetic data and mocks; they do not require
a NetConverter account or a live model. Textual tests exercise the forms and
completion/download interaction headlessly.

For a live run, obtain a dedicated pilot key, change to a separate folder holding
synthetic configs, and run the installed client. Never commit workspace state,
keys, customer configurations, conversion outputs, or private server details.

Keep model payloads limited to the existing explicit projection and typed
operation catalog. Do not add shell execution, dynamic URLs, model-controlled
paths, automatic hosted fallback, or report text as model context. New behavior
needs tests for its security boundary and failure/retry behavior.

Open a pull request with the problem, change, and relevant verification. Use
synthetic reproduction data. Public issues and CI logs must not contain secrets
or customer data. See [SECURITY.md](SECURITY.md) for private reporting.
