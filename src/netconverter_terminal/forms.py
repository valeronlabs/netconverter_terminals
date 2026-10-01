"""Structured sensitive inputs stay in the direct server channel."""

import json
from pathlib import Path
from textual.screen import ModalScreen
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Button, Label, Select, Input, Checkbox, Static


class ConversionForm(ModalScreen):
    CSS = """ConversionForm { align: center middle; } #form { width: 76; height: auto; max-height: 95%; border: thick $accent; padding: 1 2; background: $surface; overflow-y: auto; }"""

    def __init__(self, capabilities):
        super().__init__()
        self.capabilities = capabilities

    def compose(self) -> ComposeResult:
        with Vertical(id="form"):
            yield Label("ASA → Palo Alto · conversion choices")
            for field, key, label in [
                ("target_vendor", "targets", "Output"),
                ("panos_target_version", "panos_versions", "PAN-OS version"),
                ("routing_engine", "routing_engines", "Routing engine"),
                ("pipeline_mode", "pipeline_modes", "Conversion mode"),
            ]:
                yield Label(label)
                yield Select(
                    [(v, v) for v in self.capabilities[key]],
                    prompt="Select " + label,
                    id=field,
                )
            yield Input(
                placeholder="Panorama device group (required for Panorama)",
                id="device_group",
            )
            yield Input(
                placeholder="Panorama template (required for Panorama)", id="template"
            )
            yield Checkbox(
                "Remove unused objects through the validated migration pipeline",
                id="cleanup",
            )
            yield Select(
                [
                    ("Use selected mode’s App-ID setting", "preset"),
                    ("Enable App-ID", "on"),
                    ("Disable App-ID", "off"),
                ],
                prompt="App-ID override (optional)",
                id="appid",
            )
            yield Select([("App-ID: stack above original", "dual_stack"), ("App-ID: replace original", "force")], prompt="App-ID implementation (mode preset if blank)", id="app_id_implementation")
            for field, label in [("add_security_profiles", "Security profiles"), ("log_all_rules", "Log all rules"), ("implicit_deny", "Explicit deny-all")]:
                yield Label(label)
                yield Select([("Use mode preset", "preset"), ("Enable", "on"), ("Disable", "off")], value="preset", id=field)
            yield Input(placeholder="Default security profile group (optional)", id="default_profile_group")
            yield Input(placeholder='Zone mapping JSON, e.g. {"inside":"Trust"} (optional)', id="zone_mapping")
            yield Static("", id="error")
            yield Button("Submit conversion", id="submit", variant="primary")
            yield Button("Cancel", id="cancel")

    def on_button_pressed(self, event):
        if event.button.id == "cancel":
            self.dismiss(None)
            return
        options = {}
        for field in (
            "target_vendor",
            "panos_target_version",
            "routing_engine",
            "pipeline_mode",
        ):
            value = self.query_one("#" + field, Select).value
            if value is Select.NULL:
                self.query_one("#error", Static).update("Choose each required setting.")
                return
            options[field] = value
        if options["target_vendor"] == "palo_alto_panorama":
            for field, widget in [
                ("panorama_device_group", "device_group"),
                ("panorama_template", "template"),
            ]:
                value = self.query_one("#" + widget, Input).value.strip()
                if not value:
                    self.query_one("#error", Static).update(
                        "Panorama requires a device group and template."
                    )
                    return
                options[field] = value
        options["remove_unused_objects"] = self.query_one("#cleanup", Checkbox).value
        appid = self.query_one("#appid", Select).value
        if appid in {"on", "off"}:
            options["enable_appid"] = appid == "on"
        implementation = self.query_one("#app_id_implementation", Select).value
        if implementation is not Select.NULL:
            options["app_id_implementation"] = implementation
        for field in ("add_security_profiles", "log_all_rules", "implicit_deny"):
            value = self.query_one("#" + field, Select).value
            if value in {"on", "off"}:
                options[field] = ("explicit-deny-all" if value == "on" else "none") if field == "implicit_deny" else value == "on"
        profile = self.query_one("#default_profile_group", Input).value.strip()
        if profile:
            options["default_profile_group"] = profile
        mapping = self.query_one("#zone_mapping", Input).value.strip()
        if mapping:
            try:
                parsed = json.loads(mapping)
                if not isinstance(parsed, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in parsed.items()):
                    raise ValueError()
                options["zone_mapping"] = parsed
            except (ValueError, TypeError):
                self.query_one("#error", Static).update("Zone mapping must be a JSON object of source and target names.")
                return
        self.dismiss(options)


class OpenForm(ModalScreen):
    CSS = ConversionForm.CSS.replace("ConversionForm", "OpenForm")

    def __init__(self, root):
        super().__init__()
        self.root = Path(root)

    def compose(self):
        with Vertical(id="form"):
            yield Label("Open configuration from " + str(self.root))
            files = sorted(p.name for p in self.root.iterdir() if p.is_file() and p.suffix.lower() in {".cfg", ".conf", ".txt", ".set", ".xml"} and not p.name.startswith(("tra_", "trm_", "psc_", "opt_")))
            yield Select([(p, p) for p in files], prompt="Choose a file", id="file")
            yield Input(placeholder="Or relative path in this folder", id="path")
            yield Select([(x, x) for x in ["cisco_asa", "palo_alto_set", "palo_alto_xml", "palo_alto_panorama"]], value="cisco_asa", id="vendor")
            yield Static("Selected file is uploaded directly to NetConverter over the configured encrypted connection.")
            yield Button("Open and upload", id="open", variant="primary")
            yield Button("Cancel", id="cancel")

    def on_button_pressed(self, event):
        if event.button.id == "cancel":
            self.dismiss(None)
            return
        filename = self.query_one("#path", Input).value.strip() or self.query_one("#file", Select).value
        if filename is not Select.NULL:
            self.dismiss((filename, self.query_one("#vendor", Select).value))
