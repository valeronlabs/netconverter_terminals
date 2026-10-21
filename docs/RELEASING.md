# Releasing the NetConverter CLI

A release is a `v<version>` tag on the public repository
`valeronlabs/netconverter_terminals`. The [Release workflow](../.github/workflows/release.yml)
then tests and builds the package, publishes it to PyPI as
[`netconverter-cli`](https://pypi.org/project/netconverter-cli/) with trusted publishing
(no API token anywhere), and only then creates the GitHub Release with the wheel and
`SHA256SUMS`. `netconverter update` reads that GitHub Release; PyPI installs upgrade with
`uv tool upgrade netconverter-cli`.

The workflow runs only in the public repository; the private development repository can
carry the same file without publishing anything.

## One-time setup (founder)

Do these once, before the first tag. Nothing can be published until they exist.

1. **PyPI account.** Sign in to <https://pypi.org> with the ValeronLabs account (create it
   if needed) and turn on two-factor authentication (required for publishing).
2. **Pending trusted publisher** (this also reserves the name; `netconverter-cli` is free
   on PyPI today). PyPI → *Your account* → **Publishing** →
   *Add a new pending publisher* → **GitHub**:

   | Field | Value |
   |---|---|
   | PyPI Project Name | `netconverter-cli` |
   | Owner | `valeronlabs` |
   | Repository name | `netconverter_terminals` |
   | Workflow name | `release.yml` |
   | Environment name | `pypi` |

   The project is created on the first successful publish; the pending publisher then
   becomes a normal trusted publisher of that project.
3. **GitHub environment.** <https://github.com/valeronlabs/netconverter_terminals> →
   *Settings* → *Environments* → **New environment** → `pypi`. Recommended:
   *Required reviewers* = the founder (each publish waits for approval) and
   *Deployment branches and tags* → *Selected* → tag rule `v*`.
4. **Optional, after the first publish:** on PyPI add a second owner (a team account)
   so the project is not tied to one person.

## Each release

1. In the private repo (`devnexthop/netconverter_terminals`), on `main`:
   - set the version in `pyproject.toml` and `src/netconverter_cli/__init__.py`;
   - `uv lock` (updates the project version in `uv.lock`);
   - add a `## <version> — <date>` section at the top of `CHANGELOG.md` (it becomes the
     release notes);
   - `uv run pytest tests -q`, `uv build`, `uvx twine check --strict dist/*`;
   - commit and push.
2. Cherry-pick those commits onto the public repo's `main` (unrelated histories: never
   read-tree or force-push), run the tests there, push.
3. Tag the public repo and push the tag:
   ```sh
   git -C ~/gitsync/netconverter_terminals-public tag -a v<version> -m "NetConverter CLI <version>"
   git -C ~/gitsync/netconverter_terminals-public push origin v<version>
   ```
4. Approve the `pypi` deployment in the workflow run (if reviewers are required). The
   workflow refuses a tag that does not match `pyproject.toml`, `__init__.py` and a
   `CHANGELOG.md` section.
5. Check:
   ```sh
   uvx --from netconverter-cli==<version> netconverter --version
   netconverter update --check
   ```
   and that the GitHub Release has `netconverter_cli-<version>-py3-none-any.whl` and
   `SHA256SUMS`.

A version already on PyPI cannot be uploaded again. If the PyPI job fails after the
upload (rare), re-run only the `github-release` job; to fix a bad release, publish the
next patch version.

## Installers

`scripts/install.sh` and `scripts/install.ps1` are the sources of
<https://netconverter.ai/install.sh> and <https://netconverter.ai/install.ps1>. The website
serves them unchanged, as `text/plain`; copy them over whenever they change here. They
install from PyPI and fall back to the latest GitHub Release wheel (after a SHA-256
check), so they also work before the first PyPI publish.

## MCP Registry

The README carries `<!-- mcp-name: ai.netconverter/netconverter -->`, which the
[Official MCP Registry](https://registry.modelcontextprotocol.io) checks in the PyPI
description to prove the package belongs to the server entry. After the first PyPI
release, publish a `server.json` for `ai.netconverter/netconverter` (package
`netconverter-cli`, registry `pypi`, transport `stdio`, arguments `mcp`) with
`mcp-publisher`, authenticating the `ai.netconverter` namespace through the
`netconverter.ai` domain (DNS TXT record).
