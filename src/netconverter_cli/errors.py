"""What a failed command tells the person, and the exit code scripts can test (#9, #10).

One place for the wording, so the CLI, the full-screen app and first-run setup
say the same thing. Exit codes are documented in docs/COMMANDS.md.
"""

from __future__ import annotations

import re

EXIT_FAILURE = 1    # the command ran but did not succeed (a change not applied, an update failed)
EXIT_USAGE = 2      # wrong command line: unknown command, missing or invalid argument
EXIT_AUTH = 3       # not signed in, sign-in rejected or locked, or the credential lacks the entitlement
EXIT_INPUT = 4      # the input was refused: a local file, --options, or the server's 4xx reason
EXIT_SERVER = 5     # NetConverter could not be reached or failed (connection, 429, 5xx)
EXIT_CANCELLED = 130  # Ctrl-C (128 + SIGINT)

CANCELLED = "Cancelled. Nothing was saved."
SIGNED_OUT = ("You are not signed in to NetConverter. Sign in with `netconverter login` "
              "(`netconverter login --clerk` for your NetConverter account), then retry.")
KEYRING_LOCKED = ("Your system keyring is locked, so NetConverter can't read your sign-in. "
                  "Unlock it, or sign in again with `netconverter login`.")
OPTIONS_EXAMPLE = """--options '{"panos_target_version":"12.1"}'"""


class CommandError(SystemExit):
    """A message for stderr plus its exit code.

    A SystemExit, so callers that already stop on SystemExit keep working;
    ``cli.main`` prints the message once.
    """

    def __init__(self, message: str, code: int = EXIT_FAILURE):
        super().__init__(code)
        self.message = message

    def __str__(self) -> str:
        return self.message


def api_exit_code(exc) -> int:
    if exc.status in (401, 403):
        return EXIT_AUTH
    if exc.status in (400, 404, 409, 413, 422):
        return EXIT_INPUT
    return EXIT_SERVER


# The server's 403 reasons (External API authdep/jobs), in words a person can act on.
_ENTITLEMENT = {
    "insufficient scope": "your credential does not include the permission this action needs",
    "tenant not active": "your NetConverter organisation is not active yet (NetConverter approves new accounts)",
    "tenant not found": "your sign-in is not linked to a NetConverter organisation yet",
    "terminal profile is restricted to quick operations":
        "a terminal pilot key runs only the ASA → Palo Alto quick jobs",
    "guided profile is restricted to preparation": "a guided-workflow credential can only prepare drafts",
    "trial_expired": "your trial has ended",
}
_FEATURE = re.compile(r"['\"]feature['\"]\s*:\s*['\"]([A-Za-z0-9_ -]{1,60})['\"]")


def entitlement(exc) -> str:
    """A 403 as what is missing, never a bare "forbidden"."""
    message = (getattr(exc, "message", "") or "").strip()
    detail = exc.detail if isinstance(exc.detail, dict) else {}
    feature = detail.get("feature") if isinstance(detail.get("feature"), str) else None
    match = _FEATURE.search(message)
    if feature or match:
        reason = f"your plan does not include the {(feature or match.group(1)).replace('_', ' ')} feature"
    else:
        reason = (_ENTITLEMENT.get(message.lower()) or _ENTITLEMENT.get(str(exc.code))
                  or message or "your credential is not entitled to this action")
    return (f"NetConverter refused this for your credential: {reason} "
            f"(HTTP 403, request {exc.request_id or 'unavailable'}). `netconverter capabilities` shows "
            "what it can do; ask NetConverter to add what is missing.")


def api_error_message(exc, *, max_bytes: int | None = None) -> str:
    """One sentence for an APIError, with the server's own reason when it gave one."""
    reason = getattr(exc, "message", "") or ""
    if exc.status == 401:
        return SIGNED_OUT
    if exc.status == 403:
        return entitlement(exc)
    if exc.status == 0:
        return "Connection interrupted. /resume recovers a pending submission."
    if exc.status == 413 and not reason and max_bytes:
        return f"The configuration exceeds your {max_bytes:,}-byte limit."
    if exc.status == 422 and not reason:
        return "NetConverter could not accept these choices. Review them and retry."
    if exc.status == 429 and not reason:
        return "A usage or active-job limit was reached. Check /jobs and /refresh."
    if reason:
        return f"NetConverter refused the request: {reason} (HTTP {exc.status}, request {exc.request_id or 'unavailable'})."
    return f"Server request failed (HTTP {exc.status}). Retry, or contact NetConverter with the job ID."
