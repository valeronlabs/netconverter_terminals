"""Which job options a client may send, checked here before anything is uploaded (#11, #19).

The full External API (``POST /jobs``) honours a few body keys and a YAML v2
decisions document (``yaml_v2``); any other body key is accepted and silently
ignored by the server (tra_d0aabfe690d2). So:

* ``BODY_OPTIONS`` go on the request body as given;
* ``DECISION_OPTIONS`` (the guided screens' settings, and the pilot API's flat
  option names) are mapped into the ``yaml_v2`` sections the worker reads:
  ``zone_mapping``, ``options``, ``pa_target`` and ``output_platform``;
* ``QUICK_ONLY_OPTIONS`` exist only on the pilot API and are refused on the
  full API;
* anything else, and every ``RESERVED`` request field, is refused naming it.

The pilot API (``quick/jobs``) maps the same flat names into YAML v2 itself,
so a pilot key sends them as they are.

Sources: aws-netconverter.ai ``app/api/v1/public/jobs.py`` (``selected_device_groups``,
``optimization_options``, ``yaml_v2``, ``file_name``), ``app/services/terminal_quick/engine.py``
(the pilot's flat names and their YAML v2 placement), the YAML v2 schema
(``TranslationOptions``, ``PaloAltoTargetConfig``) and the worker's
``_build_user_decisions_from_yaml_v2``. Every key here has a known type.
"""

from __future__ import annotations

import copy
import re

from .workspace import WorkspaceError

# Request fields the client sets itself; never accepted from options.
RESERVED = frozenset({
    "source_config", "file_id", "source_vendor", "target_vendor", "technology", "device_type",
    "job_type", "configuration_id", "yaml", "manual_mappings", "mapping_file_id", "mapping_yaml",
    "operation", "options",
})
OPTIMIZATION_FLAGS = ("enable_rag", "enable_ai_fixes", "enable_deep_analysis", "enable_graph_analysis")
_VERSION = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")
YAML_V2_SCHEMA_VERSION = "2.0"


class OptionsError(WorkspaceError):
    """A job option the server would refuse or silently ignore; the message names it."""


def _text(limit):
    return {"type": "string", "minLength": 1, "maxLength": limit}


# key -> (JSON schema, job types, yaml_v2 section or None for a body key)
BODY_OPTIONS = {
    "selected_device_groups": ({"type": "array", "items": _text(200), "maxItems": 500,
                                "description": "Panorama device groups to include (default: all)."},
                               ("convert", "validate", "optimize")),
    "optimization_options": ({"type": "object", "additionalProperties": False,
                              "properties": {k: {"type": "boolean"} for k in OPTIMIZATION_FLAGS},
                              "description": "Optimize only: analysis switches."}, ("optimize",)),
    "file_name": ({**_text(255), "description": "Name shown for the job in the portal."},
                  ("convert", "validate", "optimize")),
}
DECISION_OPTIONS = {
    "zone_mapping": ({"type": "object", "additionalProperties": _text(200), "maxProperties": 500,
                      "description": "Source zone -> target zone names."}, "zone_mapping"),
    "remove_unused_objects": ({"type": "boolean"}, "options"),
    "enable_appid": ({"type": "boolean"}, "options"),
    "app_id_implementation": ({"type": "string", "enum": ["dual_stack", "force"]}, "options"),
    "add_security_profiles": ({"type": "boolean"}, "options"),
    "log_all_rules": ({"type": "boolean"}, "options"),
    "implicit_deny": ({"type": "string", "enum": ["explicit-deny-all", "none"]}, "options"),
    "panos_target_version": ({"type": "string", "pattern": "^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$",
                              "description": "Palo Alto targets only, e.g. 11.2."}, "pa_target"),
    "routing_engine": ({"type": "string", "enum": ["vr", "lr"],
                        "description": "Palo Alto targets only."}, "pa_target"),
    "default_profile_group": ({**_text(63), "description": "Palo Alto targets only."}, "pa_target"),
    "panorama_device_group": ({**_text(63), "description": "Panorama target only."}, "output_platform"),
    "panorama_template": ({**_text(63), "description": "Panorama target only."}, "output_platform"),
}
QUICK_ONLY_OPTIONS = {
    "pipeline_mode": {"type": "string", "enum": ["like_for_like", "ai_recommended"]},
}
# A whole decisions document is the user's own (CLI --options / TUI); a model may not send one.
DOCUMENT_OPTION = "yaml_v2"


def _type_ok(value, schema) -> bool:
    kind = schema.get("type")
    if kind == "boolean":
        return type(value) is bool
    if kind == "string":
        if not isinstance(value, str) or not value.strip() or len(value) > schema.get("maxLength", 255):
            return False
        if "enum" in schema and value not in schema["enum"]:
            return False
        return "pattern" not in schema or bool(_VERSION.fullmatch(value))
    if kind == "array":
        return (isinstance(value, list) and len(value) <= schema.get("maxItems", 500)
                and all(_type_ok(item, schema["items"]) for item in value))
    if kind == "object":
        if not isinstance(value, dict) or len(value) > schema.get("maxProperties", 500):
            return False
        fixed = schema.get("properties")
        if fixed is not None:
            return set(value) <= set(fixed) and all(_type_ok(v, fixed[k]) for k, v in value.items())
        values = schema.get("additionalProperties")
        return all(isinstance(k, str) and k.strip() and _type_ok(v, values) for k, v in value.items())
    return False


def _expected(schema) -> str:
    if "enum" in schema:
        return "one of " + ", ".join(schema["enum"])
    if schema.get("type") == "object" and "properties" in schema:
        return "an object of booleans (" + ", ".join(schema["properties"]) + ")"
    return {"boolean": "true or false", "string": "a text value", "array": "a list of names",
            "object": "an object of names"}.get(schema.get("type"), "a value")


def check(options, job_type: str, target_vendor=None, *, profile: str | None = "external",
          allow_document: bool = True) -> dict:
    """The options unchanged when the server would honour every one; else OptionsError.

    ``profile`` is ``external`` (full API), ``quick`` (pilot key) or None (not known yet:
    only the key, type and reserved-field checks run).
    ``allow_document`` is False for model-driven callers (the MCP bridge).
    """
    if options is None:
        return {}
    if not isinstance(options, dict):
        raise OptionsError("Options must be a JSON object of job settings.")
    reserved = sorted(k for k in options if k in RESERVED or (k == DOCUMENT_OPTION and not allow_document))
    if reserved:
        raise OptionsError(f"Options cannot set {', '.join(reserved)}: "
                           + ("the file, vendors and job type come from the command itself."
                              if set(reserved) - {DOCUMENT_OPTION} else
                              "a decisions document is not accepted here."))
    known = set(BODY_OPTIONS) | set(DECISION_OPTIONS) | set(QUICK_ONLY_OPTIONS) | {DOCUMENT_OPTION}
    unknown = sorted(k for k in options if k not in known)
    if unknown:
        raise OptionsError(f"Unknown option{'s' if len(unknown) > 1 else ''} {', '.join(unknown)}; "
                           f"NetConverter would ignore {'them' if len(unknown) > 1 else 'it'}. "
                           f"Known options: {', '.join(sorted(known - {DOCUMENT_OPTION}))}.")
    for key, value in options.items():
        if key == DOCUMENT_OPTION:
            if not isinstance(value, (str, dict)):
                raise OptionsError("yaml_v2 must be YAML text or an object.")
            schema = None
        elif key in BODY_OPTIONS:
            schema = BODY_OPTIONS[key][0]
        elif key in DECISION_OPTIONS:
            schema = DECISION_OPTIONS[key][0]
        else:
            schema = QUICK_ONLY_OPTIONS[key]
        if schema is not None and not _type_ok(value, schema):
            raise OptionsError(f"Option {key} must be {_expected(schema)}.")
    if profile is None:  # credential profile not known yet: key, type and reserved checks only
        return dict(options)
    if profile == "quick":  # the pilot API maps the flat settings into YAML v2 itself
        full_only = sorted(k for k in options if k in BODY_OPTIONS or k == DOCUMENT_OPTION)
        if full_only:
            raise OptionsError(f"{', '.join(full_only)} applies only to the full API, "
                               "not to a Terminal Quick pilot key.")
        return dict(options)
    misplaced = sorted(k for k in options if k in BODY_OPTIONS and job_type not in BODY_OPTIONS[k][1])
    decisions = sorted(k for k in options if k in DECISION_OPTIONS or k == DOCUMENT_OPTION)
    if job_type != "convert":
        misplaced += decisions
    if misplaced:
        raise OptionsError(f"{', '.join(sorted(misplaced))} {'do' if len(misplaced) > 1 else 'does'} "
                           f"not apply to {job_type} jobs.")
    quick_only = sorted(k for k in options if k in QUICK_ONLY_OPTIONS)
    if quick_only:
        raise OptionsError(f"{', '.join(quick_only)} applies only to Terminal Quick pilot keys; "
                           "the full API has no such setting, so it would be ignored.")
    target = str(target_vendor or "")
    pa_only = sorted(k for k in options if DECISION_OPTIONS.get(k, (None, ""))[1] == "pa_target")
    if pa_only and not target.startswith("palo_alto"):
        raise OptionsError(f"{', '.join(pa_only)} apply only to a Palo Alto target"
                           + (f", not {target}." if target else "."))
    panorama = sorted(k for k in options if DECISION_OPTIONS.get(k, (None, ""))[1] == "output_platform")
    if panorama and target != "palo_alto_panorama":
        raise OptionsError(f"{', '.join(panorama)} apply only to the palo_alto_panorama target.")
    if isinstance(options.get(DOCUMENT_OPTION), str) and len(decisions) > 1:
        raise OptionsError("Put " + ", ".join(k for k in decisions if k != DOCUMENT_OPTION)
                           + " inside the yaml_v2 document, or drop yaml_v2.")
    return dict(options)


def external_body(options, job_type: str, target_vendor=None, *, allow_document: bool = True) -> dict:
    """Body fields for ``POST /jobs``: body options as given, decisions folded into ``yaml_v2``."""
    options = check(options, job_type, target_vendor, allow_document=allow_document)
    body = {k: v for k, v in options.items() if k in BODY_OPTIONS}
    decisions = {k: v for k, v in options.items() if k in DECISION_OPTIONS}
    document = options.get(DOCUMENT_OPTION)
    if not decisions:
        if document is not None:
            body[DOCUMENT_OPTION] = document
        return body
    document = copy.deepcopy(document) if isinstance(document, dict) else {}
    document.setdefault("meta", {}).setdefault("schema_version", YAML_V2_SCHEMA_VERSION)
    for key, value in decisions.items():
        section = DECISION_OPTIONS[key][1]
        if section == "zone_mapping":
            existing = document.setdefault("zone_mapping", {})
            if not isinstance(existing, dict):
                raise OptionsError("yaml_v2 zone_mapping must be an object to add zone_mapping to it.")
            clash = sorted(z for z, t in value.items() if z in existing and existing[z] != t)
            if clash:
                raise OptionsError(f"zone_mapping conflicts with yaml_v2 for {', '.join(clash)}.")
            existing.update(value)
            continue
        part = document.setdefault(section, {})
        if not isinstance(part, dict):
            raise OptionsError(f"yaml_v2 {section} must be an object to add {key} to it.")
        if key in part and part[key] != value:
            raise OptionsError(f"{key} conflicts with yaml_v2 {section}.{key}.")
        part[key] = value
    body[DOCUMENT_OPTION] = document
    return body


def mcp_schema() -> dict:
    """The submit_file ``options`` input schema: every accepted key typed, nothing else."""
    properties = {key: dict(schema) for key, (schema, _) in BODY_OPTIONS.items()}
    properties.update({key: dict(schema) for key, (schema, _) in DECISION_OPTIONS.items()})
    properties.update({key: {**schema, "description": "Terminal Quick pilot keys only."}
                       for key, schema in QUICK_ONLY_OPTIONS.items()})
    return {"type": "object", "properties": properties, "additionalProperties": False,
            "description": "Optional job settings. Decision settings apply to convert jobs; "
                           "no configuration text, vendors or job type."}
