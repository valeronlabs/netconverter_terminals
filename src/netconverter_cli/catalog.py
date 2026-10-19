"""What the connected server accepts, in one shape for both credential profiles.

``external`` credentials (an ``nck_*`` key or a Clerk sign-in) read
``GET /capabilities``: every vendor, source→target path and job type the full
API accepts. ``quick`` credentials (0.1.x Terminal Quick pilot keys) keep the
pilot's fixed ASA → Palo Alto surface. Menus are built from this object, never
from a list in the client.
"""

from __future__ import annotations

from dataclasses import dataclass, field

JOB_TYPES = ("convert", "validate", "optimize")
QUICK_SOURCES = ("cisco_asa", "palo_alto_set", "palo_alto_xml", "palo_alto_panorama")
QUICK_LIMIT_BYTES = 50_000
DEVICE_TYPES = ("firewall", "router", "switch")

# Names for codes a server response may not name (quick capabilities carry codes only).
NAMES = {
    "cisco_asa": "Cisco ASA",
    "palo_alto_set": "Palo Alto (Set)",
    "palo_alto_xml": "Palo Alto (XML)",
    "palo_alto_panorama": "Palo Alto (Panorama)",
}
# Human labels for option values shown in menus and the review card.
LABELS = {
    "vr": "Virtual router (vr)",
    "lr": "Logical router (lr)",
    "like_for_like": "Like for like",
    "ai_recommended": "AI recommended",
    "convert": "Convert",
    "validate": "Validate",
    "optimize": "Optimize",
    "analyze": "Validate",
}
FIELD_LABELS = {
    "source_vendor": "Source",
    "target_vendor": "Target",
    "panos_target_version": "PAN-OS",
    "routing_engine": "Routing",
    "pipeline_mode": "Mode",
    "remove_unused_objects": "Unused objects",
    "panorama_device_group": "Device group",
    "panorama_template": "Template",
    "enable_appid": "App-ID",
    "app_id_implementation": "App-ID mode",
    "add_security_profiles": "Profiles",
    "log_all_rules": "Log all rules",
    "implicit_deny": "Explicit deny",
    "default_profile_group": "Profile group",
    "zone_mapping": "Zone mapping",
    "job_type": "Job",
    "file": "File",
}


def device_type_of(code: str) -> str:
    for kind in ("router", "switch"):
        if code.endswith("_" + kind):
            return kind
    return "firewall"


@dataclass
class Catalog:
    profile: str = "unknown"  # external | quick | unknown (not loaded yet)
    vendors: dict = field(default_factory=dict)  # code -> {name, device_type, roles, input}
    paths: list = field(default_factory=list)  # [(source, target)]
    job_types: tuple = ()
    limits: dict = field(default_factory=dict)
    remaining: dict = field(default_factory=dict)
    quick: dict = field(default_factory=dict)  # pilot-only conversion settings
    trial: bool = False

    @classmethod
    def from_external(cls, caps: dict) -> "Catalog":
        vendors = {}
        for item in caps.get("vendors") or []:
            if isinstance(item, dict) and isinstance(item.get("code"), str):
                code = item["code"]
                vendors[code] = {
                    "name": str(item.get("name") or NAMES.get(code) or code),
                    "device_type": item.get("device_type") or device_type_of(code),
                    "roles": list(item.get("roles") or []),
                    "input": item.get("input") or "text",
                }
        paths = [
            (p["source"], p["target"]) for p in caps.get("paths") or []
            if isinstance(p, dict) and p.get("source") in vendors and p.get("target") in vendors
        ]
        types = tuple(t for t in caps.get("job_types") or ("convert",) if t in JOB_TYPES)
        return cls("external", vendors, paths, types or ("convert",),
                   dict(caps.get("limits") or {}), {}, {}, bool(caps.get("trial")))

    @classmethod
    def from_quick(cls, caps: dict) -> "Catalog":
        targets = [t for t in caps.get("targets") or QUICK_SOURCES[1:]]
        vendors = {code: {"name": NAMES.get(code, code), "device_type": "firewall",
                          "roles": ["source"] + (["target"] if code in targets else []),
                          "input": "text"} for code in QUICK_SOURCES}
        paths = [("cisco_asa", t) for t in targets]
        quick = {k: caps[k] for k in ("panos_versions", "routing_engines", "pipeline_modes") if caps.get(k)}
        limits = {"max_config_bytes": (caps.get("limits") or {}).get("max_config_bytes") or QUICK_LIMIT_BYTES}
        return cls("quick", vendors, paths, JOB_TYPES, limits,
                   dict(caps.get("remaining") or {}), quick)

    # -- questions the menus ask ---------------------------------------------

    @property
    def loaded(self) -> bool:
        return bool(self.vendors)

    @property
    def max_bytes(self) -> int:
        value = self.limits.get("max_config_bytes")
        return value if isinstance(value, int) and value > 0 else QUICK_LIMIT_BYTES

    def name(self, code: str | None) -> str:
        if not code:
            return "—"
        return self.vendors.get(code, {}).get("name") or NAMES.get(code) or code

    def sources(self, job_type: str = "convert") -> list[str]:
        """Sources this job type can start from, uploadable as a text file."""
        with_paths = {s for s, _ in self.paths}
        return [
            code for code, v in self.vendors.items()
            if "source" in v["roles"] and v["input"] == "text"
            and (job_type != "convert" or code in with_paths)
        ]

    def targets(self, source: str) -> list[str]:
        return [t for s, t in self.paths if s == source]

    def grouped(self, codes: list[str]) -> list[tuple[str, str]]:
        """(label, code) ordered firewall → router → switch, device type shown when ambiguous."""
        names = [self.name(c) for c in codes]
        out = []
        for kind in DEVICE_TYPES:
            for code in (c for c in codes if self.vendors.get(c, {}).get("device_type", "firewall") == kind):
                label = self.name(code)
                if names.count(label) > 1:
                    label += f" · {kind}"
                out.append((label, code))
        return out

    def supports(self, job_type: str) -> bool:
        return job_type in self.job_types

    def describe(self) -> str:
        if self.profile == "quick":
            return "Pilot key · ASA → Palo Alto"
        if not self.loaded:
            return ""
        return f"{len([v for v in self.vendors.values() if 'source' in v['roles']])} sources · {len(self.paths)} paths"


def label(value) -> str:
    if isinstance(value, bool):
        return "Yes" if value else "No"
    return LABELS.get(value, str(value)) if isinstance(value, str) else str(value)
