# NetConverter Terminal

**ASA → Palo Alto SET, XML, and Panorama, from the folder containing your configuration.**

NetConverter — by ValeronLabs LLC.

A lightweight terminal client for NetConverter migration and configuration analysis.
Choose an ASA file, answer inline conversion questions, track the server job, and retrieve the
converted configuration, YAML mappings, reports, and evidence beside your source.
The interface uses NetConverter’s dark theme and blue accents, a compact welcome
screen, inline keyboard choices, readable job/results tables, and a persistent
command prompt. There are no modal forms or oversized buttons.
Use `/model` to test or repair your model connection in place. A plain command mode
is also available.

```text
NETCONVERTER                                     PILOT
ASA → Palo Alto only · SET / XML / Panorama

/convert → choose an ASA file → review settings → submit
Analyze ASA or Palo Alto configs for unused objects, routes, and traffic policy.
```

## Start here

1. Obtain a **terminal pilot API key** from your NetConverter contact. Enrollment
   is currently assisted; downloading the client does not provision an account.
2. Follow the [Mac quick start](QUICK_START.md) to install the client and run
   `netconverter` in your configuration folder.
3. Accept the production API address `https://api.netconverter.ai/external/v1`,
   enter your key in the hidden prompt, and optionally connect a model.
4. Start with the included [synthetic ASA example](examples/demo-asa.cfg).

You do not need a local NetConverter server, Docker, AWS access, or a GitHub account
to use a published wheel. This repository contains the **client only**; the
conversion engine and hosted service are separate.

## What it does

| Workflow | Available behavior |
| --- | --- |
| Migration | ASA to Palo Alto SET, XML, or Panorama, with server-validated settings |
| Configuration analysis | ASA and supported Palo Alto inputs; unused objects, dependencies, interfaces, routes, NAT, and policy findings |
| Traffic questions | Explicit flow parameters and the server's supported policy analysis, with coverage limits |
| Optimization | Recommendations and evidence; report-only results do not claim to rewrite your configuration |
| Cleanup during migration | Optional unused-object removal through the validated conversion pipeline |
| Jobs and artifacts | Visible `trm_` conversion IDs, server status, restart/resume, SHA-256-verified downloads |
| Optional models | Anthropic, OpenAI, Gemini, or local Ollama; guided commands work without a model |

The model selects a permitted operation. It does not run a shell, read arbitrary
files, generate conversion settings, or receive detailed configuration results.
See [privacy and data flow](docs/PRIVACY.md) for the precise boundary and current
verification limits.

## Pilot allowance

An explicitly approved pilot may have a different conversion allowance. The
terminal displays the server-authorized value, including Unlimited; installing or
reinstalling the client does not change it. The 50,000-byte cap still applies.

- **50,000 bytes** per submitted configuration (not 50,000 lines).
- **3 conversion targets**, **20 analysis/optimization jobs**, and **100 follow-up
  queries** per account per UTC day.
- **One active job** per account.
- Polling and artifact downloads do not consume another job allowance.

Each output target counts separately. The server's capabilities and allowance
responses are authoritative. Larger migrations require an arrangement with
NetConverter. Runtime depends on content, settings, and server load; there is no
five-minute guarantee.

## Documentation

- [Install, connect, and run your first conversion](QUICK_START.md)
- [Commands, conversion settings, and troubleshooting](docs/COMMANDS.md)
- [Privacy, credentials, encryption, and local files](docs/PRIVACY.md)
- [What has been tested and what remains open](docs/VERIFICATION.md)
- [Development and contributing](CONTRIBUTING.md)
- [Security reporting](SECURITY.md)
- [Release notes](CHANGELOG.md)

This is a **public pilot client**. macOS is the exercised customer platform;
Windows acceptance remains pending. The client is [MIT licensed](LICENSE).
The license does not grant access to the hosted service or license the server code.
