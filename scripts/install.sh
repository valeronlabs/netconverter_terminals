#!/bin/sh
# NetConverter CLI installer for macOS and Linux.
#
#   curl -LsSf https://netconverter.ai/install.sh | sh
#   curl -LsSf https://netconverter.ai/install.sh | sh -s -- --yes --workspace ~/configs
#
# Installs uv (if missing) and `netconverter-cli` from PyPI, falling back to the
# latest GitHub release wheel after checking its SHA-256. Then signs you in and
# connects your AI assistants to a workspace folder. Safe to run again: each step
# skips what is already done. It never asks for, prints or stores a secret.
set -eu

PACKAGE="netconverter-cli"
REPO="valeronlabs/netconverter_terminals"
PYTHON="3.12"
YES=0
CONNECT=1
WORKSPACE="${HOME}/migrations"

usage() {
    cat <<USAGE
NetConverter CLI installer

Usage: install.sh [--yes] [--no-connect] [--workspace PATH]

  --yes             never prompt (IT/MDM); sign-in is skipped without a terminal
  --no-connect      install and sign in only; do not connect AI assistants
  --workspace PATH  folder your AI may hand to NetConverter (default: ~/migrations)
  -h, --help        show this help
USAGE
}

say() { printf '\033[1m==>\033[0m %s\n' "$*"; }
warn() { printf 'warning: %s\n' "$*" >&2; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }

while [ $# -gt 0 ]; do
    case "$1" in
        -y|--yes) YES=1 ;;
        --no-connect) CONNECT=0 ;;
        --workspace)
            [ $# -ge 2 ] || die "--workspace needs a folder"
            WORKSPACE="$2"
            shift ;;
        --workspace=*) WORKSPACE="${1#--workspace=}" ;;
        -h|--help) usage; exit 0 ;;
        *) usage >&2; die "unknown option: $1" ;;
    esac
    shift
done

case "$WORKSPACE" in
    \~) WORKSPACE="$HOME" ;;
    \~/*) WORKSPACE="${HOME}/${WORKSPACE#\~/}" ;;
esac

# A terminal we can talk to, even when this script arrives on stdin through a pipe.
have_tty() { (exec </dev/tty) 2>/dev/null; }

need() { command -v "$1" >/dev/null 2>&1 || die "$1 is required but was not found"; }

need curl
need uname

# -- 1. uv ----------------------------------------------------------------

PATH="${HOME}/.local/bin:${HOME}/.cargo/bin:${PATH}"
export PATH

if command -v uv >/dev/null 2>&1; then
    say "uv $(uv --version 2>/dev/null | awk '{print $2}') is already installed"
else
    say "Installing uv (https://docs.astral.sh/uv)"
    curl -LsSf https://astral.sh/uv/install.sh | sh
    command -v uv >/dev/null 2>&1 || die "uv was installed but is not on PATH; open a new terminal and run this again"
fi

# -- 2. netconverter-cli --------------------------------------------------

sha256() {
    if command -v sha256sum >/dev/null 2>&1; then
        sha256sum "$1" | awk '{print $1}'
    elif command -v shasum >/dev/null 2>&1; then
        shasum -a 256 "$1" | awk '{print $1}'
    else
        die "no sha256sum or shasum to verify the download"
    fi
}

install_from_release() {
    tag=$(curl -fsSL "https://api.github.com/repos/${REPO}/releases/latest" \
        | sed -n 's/.*"tag_name": *"\(v[0-9][0-9]*\.[0-9][0-9]*\.[0-9][0-9]*\)".*/\1/p' | head -n 1)
    [ -n "$tag" ] || die "could not find the latest release of ${REPO}"
    version="${tag#v}"
    wheel="netconverter_cli-${version}-py3-none-any.whl"
    base="https://github.com/${REPO}/releases/download/${tag}"
    tmp=$(mktemp -d)
    trap 'rm -rf "$tmp"' EXIT
    say "Downloading ${wheel} and SHA256SUMS from the ${tag} release"
    curl -fsSL -o "${tmp}/${wheel}" "${base}/${wheel}" || die "could not download ${wheel}"
    curl -fsSL -o "${tmp}/SHA256SUMS" "${base}/SHA256SUMS" || die "could not download SHA256SUMS"
    want=$(awk -v f="$wheel" '$2 == f || $2 == "*" f {print tolower($1)}' "${tmp}/SHA256SUMS" | head -n 1)
    [ -n "$want" ] || die "SHA256SUMS has no entry for ${wheel}"
    got=$(sha256 "${tmp}/${wheel}")
    [ "$got" = "$want" ] || die "checksum mismatch for ${wheel}; nothing was installed"
    say "SHA-256 verified: ${wheel}"
    uv tool install --quiet --python "$PYTHON" --force "${tmp}/${wheel}"
}

# A copy installed from a wheel file stays on it unless replaced; --force moves it to PyPI.
force=""
receipt="$(uv tool dir)/${PACKAGE}/uv-receipt.toml"
if [ -f "$receipt" ] && grep -Eq '^requirements = .*(path|url|git|directory|editable) = ' "$receipt"; then
    force="--force"
fi
say "Installing ${PACKAGE} from PyPI"
# shellcheck disable=SC2086  # $force is empty or one flag
if ! uv tool install --quiet --python "$PYTHON" --upgrade $force "$PACKAGE"; then
    warn "PyPI install failed; using the latest GitHub release instead"
    install_from_release
fi
uv tool update-shell >/dev/null 2>&1 || true

NC="$(uv tool dir --bin)/netconverter"
[ -x "$NC" ] || die "netconverter was not found in $(uv tool dir --bin)"
say "$("$NC" --version 2>/dev/null || echo "netconverter is installed")"

# -- 3. sign in -----------------------------------------------------------

if "$NC" whoami 2>/dev/null | grep -q '"signed_in": true'; then
    say "Already signed in to NetConverter"
elif have_tty; then
    say "Signing in to NetConverter (your browser opens)"
    "$NC" login --clerk </dev/tty || warn "sign-in did not finish; run: netconverter login --clerk"
else
    warn "no terminal for sign-in; each user runs: netconverter login --clerk"
fi

# -- 4. workspace and assistants -------------------------------------------

mkdir -p "$WORKSPACE"
say "Workspace: ${WORKSPACE}"

if [ "$CONNECT" -eq 1 ]; then
    if [ "$YES" -eq 1 ]; then
        say "Connecting every AI assistant found on this computer"
        "$NC" --workspace "$WORKSPACE" connect --all --yes
    elif have_tty; then
        say "Connecting AI assistants (each change is shown before it is made)"
        "$NC" --workspace "$WORKSPACE" connect --all </dev/tty
    else
        warn "no terminal to confirm changes; run: netconverter --workspace \"${WORKSPACE}\" connect --all"
    fi
fi

cat <<DONE

NetConverter CLI is ready.
  • Put the configurations you want to work on in ${WORKSPACE}
  • Fully quit and reopen each AI assistant, then ask: "What NetConverter tools do you have?"
  • Open a new terminal if \`netconverter\` is not found yet
  • netconverter update keeps it current
DONE
