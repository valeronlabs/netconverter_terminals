"""User-controlled exposure levels for the local MCP bridge (#13).

The level says how much of a job's results an AI assistant may see:

* ``none``     verdicts, statuses, counts and ids only;
* ``masked``   the server's strict view (names as tokens), addresses masked here too;
* ``selected`` masked, plus the result sections the user chose;
* ``full``     the results as the server serves them for this tenant.

Secrets (pre-shared keys, SNMP communities, password hashes, passwords) are
stripped from every result at every level, here on the client.

The level is stored per workspace in ``.netconverter/privacy.json`` (default
``masked``). Lowering it needs nothing; raising it needs a phrase typed in a real
terminal, so neither an MCP tool nor a model can raise it. Every change is
appended to ``.netconverter/privacy-audit.jsonl``. The workspace state folder is
never a path the bridge reads or writes for a model. This module is never
exposed as a model tool.
"""

from __future__ import annotations

import getpass
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

LEVELS = ("none", "masked", "selected", "full")
RANK = {level: rank for rank, level in enumerate(LEVELS)}
DEFAULT_LEVEL = "masked"
# 0.4.x view names: strict is masked, full is full.
ALIASES = {"strict": "masked", "default": "full"}
STATE_FILE = "privacy.json"
AUDIT_FILE = "privacy-audit.jsonl"
MAX_STATE_BYTES = 64_000

# Sections a user can add to ``selected``: remote tools beyond the strict set, and
# the content calls the strict view refuses (#13: per section now, per object later).
SECTIONS = {
    "interfaces": frozenset({"get_interface_summary", "get_zone_summary"}),
    "routes": frozenset({"get_route_summary"}),
    "policy": frozenset({"get_acl_summary", "list_rules_matching", "simulate_flow"}),
    "nat": frozenset({"get_nat_summary"}),
    "vpn": frozenset({"get_vpn_summary"}),
    "objects": frozenset({"get_object_summary", "get_object_dependencies", "get_unused_objects",
                          "list_objects_with_attribute", "get_dependency_chains",
                          "get_critical_object_impact"}),
    "management": frozenset({"get_management_config"}),
    "translation": frozenset({"get_translation_edge_summary", "compare_against_intent", "query_ir"}),
    # Content the strict view refuses: get_evidence section=unparsed_lines,
    # get_job_brief focus=target and get_target_config, fetch of a job (not kb:) id.
    "unparsed_lines": frozenset(),
    "target": frozenset({"get_target_config"}),
    "reports": frozenset(),
}


class ExposureError(ValueError):
    """A level change that was refused; the message is safe to print."""


@dataclass(frozen=True)
class Exposure:
    level: str
    sections: tuple = ()

    def __post_init__(self):
        if self.level not in RANK:
            raise ExposureError(f"Unknown exposure level {self.level!r}; choose one of {', '.join(LEVELS)}")
        sections = tuple(sorted(set(self.sections))) if self.level == "selected" else ()
        unknown = [s for s in sections if s not in SECTIONS]
        if unknown:
            raise ExposureError(f"Unknown section {unknown[0]!r}; choose from {', '.join(SECTIONS)}")
        object.__setattr__(self, "sections", sections)

    @property
    def strict(self) -> bool:
        return self.level != "full"

    def section_tools(self) -> frozenset:
        return frozenset().union(*(SECTIONS[s] for s in self.sections)) if self.sections else frozenset()

    def lifts(self, name: str, arguments) -> bool:
        """A chosen section lifts the strict view's refusal of this content call."""
        if self.level != "selected":
            return False
        args = arguments if isinstance(arguments, dict) else {}
        if name == "get_evidence" and str(args.get("section", "")).strip() == "unparsed_lines":
            return "unparsed_lines" in self.sections
        if name == "get_job_brief" and str(args.get("focus", "")) == "target":
            return "target" in self.sections
        if name == "fetch":
            return "reports" in self.sections
        return False

    def describe(self) -> str:
        if self.level == "selected":
            return f"selected ({', '.join(self.sections) or 'no sections'})"
        return self.level


def normalize(level) -> str:
    text = str(level or "").strip().lower()
    text = ALIASES.get(text, text)
    if text not in RANK:
        raise ExposureError(f"Unknown exposure level {level!r}; choose one of {', '.join(LEVELS)}")
    return text


def lower(a: Exposure, b: Exposure) -> Exposure:
    """The narrower of two exposures; two ``selected`` keep only the sections both chose."""
    if RANK[a.level] != RANK[b.level]:
        return a if RANK[a.level] < RANK[b.level] else b
    if a.level == "selected":
        return Exposure("selected", tuple(set(a.sections) & set(b.sections)))
    return a


def is_raise(old: Exposure, new: Exposure) -> bool:
    if RANK[new.level] != RANK[old.level]:
        return RANK[new.level] > RANK[old.level]
    return new.level == "selected" and not set(new.sections) <= set(old.sections)


def _state_dir(root) -> Path:
    return Path(root if root is not None else ".").resolve() / ".netconverter"


def state_path(root) -> Path:
    return _state_dir(root) / STATE_FILE


def audit_path(root) -> Path:
    return _state_dir(root) / AUDIT_FILE


_warned: set = set()


def _warn_once(key, message: str) -> None:
    if key not in _warned:
        _warned.add(key)
        print(f"netconverter: {message}", file=sys.stderr)


def _audit_tail(root) -> list[dict]:
    try:
        with audit_path(root).open("rb") as stream:
            stream.seek(0, os.SEEK_END)
            stream.seek(max(0, stream.tell() - 65536))
            lines = stream.read().decode("utf-8", "replace").splitlines()
    except OSError:
        return []
    out = []
    for line in lines:
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if isinstance(entry, dict):
            out.append(entry)
    return out


def _audited(root, stored: Exposure) -> bool:
    """The stored level is the audit log's latest, reached by a typed raise at or above it."""
    entries = _audit_tail(root)
    try:
        last = Exposure(entries[-1]["new"], tuple(entries[-1].get("sections") or ()))
    except (IndexError, KeyError, TypeError, ExposureError):
        return False
    if last != stored:
        return False
    for entry in entries:
        try:
            reached = Exposure(entry["new"], tuple(entry.get("sections") or ()))
        except (KeyError, TypeError, ExposureError):
            continue
        if entry.get("confirmed") == "tty" and not is_raise(reached, stored):
            return True
    return False


def load(root) -> Exposure:
    """The workspace's level. A raise without its confirmed audit entry counts as masked."""
    path = state_path(root)
    default = Exposure(DEFAULT_LEVEL)
    try:
        if path.is_symlink() or path.stat().st_size > MAX_STATE_BYTES:
            raise ValueError
        data = json.loads(path.read_text(encoding="utf-8"))
        stored = Exposure(normalize(data["level"]), tuple(data.get("sections") or ()))
    except FileNotFoundError:
        return default
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        _warn_once(("invalid", str(path)), f"{path} is not a valid exposure setting; using {DEFAULT_LEVEL}")
        return default
    if is_raise(default, stored) and not _audited(root, stored):
        _warn_once(("unaudited", str(path)),
                   f"{path} says {stored.describe()}, but the audit log has no confirmed raise to it; "
                   f"using {DEFAULT_LEVEL}. Set it with `netconverter privacy level` in a terminal.")
        return default
    return stored


def _interactive() -> bool:
    try:
        return sys.stdin.isatty() and sys.stdout.isatty()
    except (AttributeError, ValueError):
        return False


def set_level(root, level, sections=None, *, interactive=None, ask=input, user=None):
    """Change the workspace level; returns (old, new). Raising needs a typed confirmation in a TTY."""
    new = Exposure(normalize(level), tuple(sections or ()))
    if sections and new.level != "selected":
        raise ExposureError("Sections apply only to the selected level")
    old = load(root)
    if new == old:
        return old, new
    confirmed = "not_needed"
    if is_raise(old, new):
        if not (_interactive() if interactive is None else interactive):
            raise ExposureError(
                f"Raising the exposure level ({old.describe()} → {new.describe()}) needs a confirmation "
                "typed in a terminal; it cannot be done from a script, a pipe or an AI assistant.")
        phrase = f"raise to {new.level}"
        answer = ask(f"The assistant will see more of this folder's job results ({old.describe()} → "
                     f"{new.describe()}). Type \"{phrase}\" to confirm: ")
        if str(answer or "").strip().lower() != phrase:
            raise ExposureError(f"Raise not confirmed; the level stays {old.describe()}.")
        confirmed = "tty"
    from . import __version__

    state = _state_dir(root)
    state.mkdir(mode=0o700, exist_ok=True)
    entry = {"time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
             "old": old.level, "old_sections": list(old.sections),
             "new": new.level, "sections": list(new.sections),
             "user": user or _user(), "workspace": str(state.parent), "confirmed": confirmed,
             "client_version": __version__}
    audit = audit_path(root)
    if audit.is_symlink():
        raise ExposureError(f"{audit} is a symbolic link; nothing was changed")
    fd = os.open(audit, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as stream:  # append-only: earlier lines never change
        stream.write(json.dumps(entry, sort_keys=True) + "\n")
    from .workspace import Workspace

    Workspace._atomic_replace(state_path(root), json.dumps(
        {"version": 1, "level": new.level, "sections": list(new.sections)}, indent=2).encode())
    return old, new


def _user() -> str:
    try:
        return getpass.getuser()
    except Exception:  # noqa: BLE001 - no login name on this platform
        return "unknown"


def audit_entries(root, limit: int = 20) -> list[dict]:
    """The newest audit entries, for `privacy status` in a terminal only."""
    try:
        lines = audit_path(root).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    for line in lines[-limit:]:
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


# -- result filters -----------------------------------------------------------

SECRET = "<secret>"
_SECRET_KEY_WORDS = ("password", "passwd", "passphrase", "secret", "psk", "preshared", "pre_shared",
                     "community", "private_key", "auth_key", "authentication_key", "key_string",
                     "md5_key", "shared_key")
_SECRET_WORDS = (r"pre-shared-key|preshared-key|pre_shared_key|key-string|authentication-key|auth-key|"
                 r"md5-key|passphrase|password|passwd|community|secret|psk")
_KEYWORD_VALUE = re.compile(
    rf"(?i)\b({_SECRET_WORDS})(\s+(?:[0-9]\s+)?)(\"[^\"]*\"|'[^']*'|[^\s,;]+)")
_NOT_A_VALUE = frozenset({
    "a", "an", "and", "are", "as", "be", "by", "change", "changes", "complexity", "configured", "count",
    "encrypted", "encryption", "expiry", "field", "fields", "for", "from", "hash", "hashes", "in", "is",
    "length", "level", "management", "missing", "must", "not", "of", "on", "or", "policies", "policy",
    "present", "profile", "redacted", "removed", "required", "reset", "rule", "rules", "set", "should",
    "strength", "string", "stripped", "the", "to", "type", "used", "uses", "value", "values", "was",
    "were", "with", SECRET,
})
_CRYPT = re.compile(r"\$(?:1|2[aby]?|5|6|7|8|9|y|sha1|sha512|md5)\$[^\s\"',;]+")
_FORTINET_ENC = re.compile(r"\b(ENC)\s+[A-Za-z0-9+/=]{8,}")
_PANOS_ENC = re.compile(r"-AQ==[A-Za-z0-9+/=]+")


def _secret_key(key) -> bool:
    if not isinstance(key, str):
        return False
    norm = key.lower().replace("-", "_")
    return any(word in norm for word in _SECRET_KEY_WORDS)


def _strip_text(text: str) -> str:
    def keyword(m):
        value = m.group(3)
        if value.strip("\"'").lower() in _NOT_A_VALUE:
            return m.group(0)
        return f"{m.group(1)}{m.group(2)}{SECRET}"

    text = _CRYPT.sub(SECRET, text)
    text = _PANOS_ENC.sub(SECRET, text)
    text = _FORTINET_ENC.sub(lambda m: f"{m.group(1)} {SECRET}", text)
    return _KEYWORD_VALUE.sub(keyword, text)


def strip_secrets(value, depth: int = 0):
    """Secret values out of any JSON-like value: by key name and by configuration syntax."""
    if depth > 40:
        return value
    if isinstance(value, str):
        return _strip_text(value)
    if isinstance(value, list):
        return [strip_secrets(v, depth + 1) for v in value]
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            if _secret_key(key) and (isinstance(item, str) and item or
                                     isinstance(item, list) and any(isinstance(i, str) for i in item)):
                out[key] = SECRET if isinstance(item, str) else [SECRET for _ in item]
            else:
                out[key] = strip_secrets(item, depth + 1)
        return out
    return value


# Keys whose short, token-shaped string values are verdicts, ids or categories.
_SUMMARY_KEYS = frozenset({
    "status", "verdict", "translation_status", "data_quality", "severity", "stage", "stage_key",
    "tool", "job_id", "configuration_id", "query_id", "source_vendor", "target_vendor", "vendor",
    "job_type", "view_mode", "view_mode_grant", "view_level_requested", "tier", "category", "risk",
    "readiness", "result", "outcome", "state", "kind", "code", "error", "decision", "level",
    "schema_version", "profile",
})
_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}\Z")
WITHHELD = "[withheld at exposure level none: only verdicts, statuses, counts and ids are shown]"


def summaries_only(value, depth: int = 0, key=None):
    """The ``none`` projection: booleans, numbers, nulls and allowlisted verdict/id tokens."""
    if depth > 40:
        return None
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value if key in _SUMMARY_KEYS and _TOKEN.match(value) else _DROP
    if isinstance(value, list):
        items = [summaries_only(v, depth + 1) for v in value]
        items = [v for v in items if v is not _DROP and v != {}]
        return items if items or not value else _DROP
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            projected = summaries_only(v, depth + 1, k)
            if projected is not _DROP:
                out[k] = projected
        return out if out or not value else _DROP
    return _DROP


class _Drop:
    def __repr__(self):
        return "<dropped>"


_DROP = _Drop()


def project(value, exposure: Exposure):
    """Secrets out at every level; ``none`` also reduces to verdicts and counts."""
    value = strip_secrets(value)
    if exposure.level == "none":
        value = summaries_only(value)
        return {} if value is _DROP else value
    return value
