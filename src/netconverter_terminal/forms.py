"""Structured sensitive inputs stay in the direct server channel."""

import json
from datetime import datetime
from textual import work
from pathlib import Path
from textual.screen import ModalScreen
from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll, Horizontal
from textual.widgets import Button, Label, Select, Input, Checkbox, Static, Collapsible, DataTable


class ConversionForm(ModalScreen):
    CSS = """ConversionForm { align: center middle; } #form { width: 90%; max-width: 80; height: auto; max-height: 95%; border: round $accent; padding: 1 2; background: $surface; overflow-y: auto; } .form_actions { height: 3; } .form_actions Button { width: 1fr; margin-right: 1; }"""

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
            with Vertical(id="panorama_fields"):
                yield Label("Panorama device group")
                yield Input(placeholder="Device group", id="device_group")
                yield Label("Panorama template")
                yield Input(placeholder="Template", id="template")
            yield Checkbox(
                "Remove unused objects through the validated migration pipeline",
                id="cleanup",
            )
            with Collapsible(title="Advanced settings", collapsed=True):
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
            with Horizontal(classes="form_actions"):
                yield Button("Submit conversion", id="submit", variant="primary")
                yield Button("Cancel", id="cancel")

    def on_mount(self):
        self.query_one('#panorama_fields').styles.height = 'auto'
        self.query_one('#panorama_fields').display = False

    def on_select_changed(self, event):
        if event.select.id == 'target_vendor':
            self.query_one('#panorama_fields').display = event.value == 'palo_alto_panorama'

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
    """Workspace-bounded file browser. Browsing never reads configuration content."""
    CSS = """
    OpenForm { align: center middle; background: #0a0a0b 70%; }
    OpenForm #file_form { width: 94%; height: auto; max-height: 90%; border: solid $accent; padding: 1 2; background: $background; overflow-y: auto; }
    OpenForm #files { height: 7; margin: 1 0; }
    OpenForm #file_actions { height: auto; }
    OpenForm Button { min-width: 10; width: 1fr; margin-right: 1; }
    OpenForm.compact #file_form { max-height: 100%; padding: 0 1; }
    OpenForm.compact #files { height: 4; margin: 0; }
    OpenForm #error { color: $warning; height: auto; }
    """
    BINDINGS=[('escape','cancel','Back')]

    def __init__(self, root):
        super().__init__()
        self.root=Path(root).resolve()
        self.folder=self.root
        self.entries={}
        self.selected=None

    def compose(self):
        with Vertical(id='file_form'):
            yield Label('Open configuration · 50,000 bytes maximum')
            yield Static('',id='folder',markup=False)
            yield DataTable(id='files',cursor_type='row',zebra_stripes=True)
            yield Input(placeholder='Select a row, or enter a relative file path',id='path')
            yield Label('Source format')
            yield Select([('Cisco ASA','cisco_asa'),('Palo Alto SET','palo_alto_set'),('Palo Alto XML','palo_alto_xml'),('Panorama','palo_alto_panorama')],value='cisco_asa',allow_blank=False,id='vendor')
            yield Static('Choose an action to upload only the selected file directly to NetConverter. Quick Convert is ASA only.',markup=False)
            yield Static('',id='error',markup=False)
            with Horizontal(id='file_actions'):
                yield Button('Quick Convert',id='quick_convert',variant='primary')
                yield Button('Analyze only',id='analyze_file')
                yield Button('Open',id='open')
                yield Button('Back',id='cancel')

    def on_resize(self):
        self.set_class(self.size.height<32,'compact')

    def on_mount(self):
        self.set_class(self.size.height<32,'compact')
        self.query_one('#files',DataTable).add_columns('Name','Bytes','Modified')
        self.refresh_files()

    def refresh_files(self):
        from .presentation import literal
        table=self.query_one('#files',DataTable)
        table.clear()
        self.entries={}
        self.query_one('#folder',Static).update(literal(str(self.folder)))
        items=[]
        if self.folder!=self.root:
            items.append(self.folder.parent)
        try:
            items+=sorted((p for p in self.folder.iterdir() if not p.name.startswith('.') and not p.is_symlink() and (p.is_dir() or p.suffix.lower() in {'.asa','.cfg','.conf','.txt','.set','.xml'}) and not p.name.startswith(('tra_','trm_','psc_','opt_'))),key=lambda p:(not p.is_dir(),p.name.lower()))
        except OSError:
            self.query_one('#error',Static).update('Cannot list this folder. Check its permissions.')
        for p in items:
            try:
                if not p.resolve().is_relative_to(self.root):
                    continue
                stat=p.stat()
                key=str(len(self.entries))
                self.entries[key]=p
                label='.. /' if p==self.folder.parent else p.name+('/' if p.is_dir() else '')
                size='—' if p.is_dir() else str(stat.st_size)
                table.add_row(literal(label),size,datetime.fromtimestamp(stat.st_mtime).strftime('%b %d %H:%M'),key=key)
            except OSError:
                continue
        if not items:
            self.query_one('#error',Static).update('No configuration files here. Enter a relative path or copy a config into this folder.')
        table.focus()
        self.query_one('#file_form').scroll_home(animate=False)

    def on_data_table_row_selected(self,event):
        path=self.entries.get(event.row_key.value)
        if path is None:
            return
        if path.is_dir():
            self.folder=path
            self.refresh_files()
        else:
            self.query_one('#path',Input).value=str(path.relative_to(self.root))

    def action_cancel(self):
        self.dismiss(None)

    def on_button_pressed(self,event):
        event.stop()
        if event.button.id=='cancel':
            self.dismiss(None)
            return
        filename=self.query_one('#path',Input).value.strip()
        vendor=self.query_one('#vendor',Select).value
        if not filename:
            self.query_one('#error',Static).update('Select a file with Enter or enter its relative path.')
            return
        if event.button.id=='quick_convert' and vendor!='cisco_asa':
            self.query_one('#error',Static).update('Migration supports Cisco ASA sources only. Choose Analyze only for Palo Alto.')
            return
        from .workspace import Workspace, WorkspaceError
        try:
            Workspace(self.root).snapshot(filename)
        except (WorkspaceError,OSError) as exc:
            self.query_one('#error',Static).update(str(exc) if isinstance(exc,WorkspaceError) else 'Cannot read this file. Check its permissions.')
            return
        follow={'quick_convert':'convert','analyze_file':'analyze'}.get(event.button.id)
        self.dismiss((filename,vendor,follow))


class ModelForm(ModalScreen):
    """Repair model connections without leaving the workspace or exposing a key."""
    CSS = ConversionForm.CSS.replace("ConversionForm", "ModelForm") + "ModelForm.compact #form { max-height: 100%; padding: 0 1; }"
    BINDINGS=[("escape","cancel","Cancel")]

    def __init__(self, root, current=None):
        super().__init__()
        self.root = root
        self.current = current
        self.connecting = False

    def compose(self):
        with Vertical(id='form'):
            yield Label('Model connection')
            yield Static('Models choose operations only. Configuration contents and detailed results stay out of model requests.')
            yield Label('Provider')
            yield Select([('OpenAI','openai'),('Anthropic','anthropic'),('Gemini','gemini'),('Ollama','ollama'),('None · guided commands','none')], value=self.current.name if self.current else 'openai', allow_blank=False, id='model_provider')
            yield Label('Exact API model ID')
            yield Input(value=self.current.model if self.current else '', placeholder='Enter the model ID available to your API account', id='model_id')
            yield Label('Provider API key · hidden')
            yield Input(password=True, placeholder='Paste provider key; leave blank to use a saved key', id='model_key')
            yield Static('Ollama uses your local service and needs no key. Choose None for guided commands.')
            yield Static('',id='error', markup=False)
            with Horizontal(classes='form_actions'):
                yield Button('Test and connect',id='connect_model',variant='primary')
                yield Button('Cancel',id='cancel_model')

    def on_resize(self):
        self.set_class(self.size.height<32,'compact')

    def on_mount(self):
        self.set_class(self.size.height<32,'compact')
        self.query_one('#form').scroll_home(animate=False)

    def action_cancel(self):
        if not self.connecting:
            self.query_one('#model_key',Input).value=''
            self.dismiss(None)

    def on_button_pressed(self,event):
        if self.connecting:
            return
        if event.button.id=='cancel_model':
            self.query_one('#model_key',Input).value=''
            self.dismiss(None)
        elif event.button.id=='connect_model':
            name=self.query_one('#model_provider',Select).value
            model=self.query_one('#model_id',Input).value.strip()
            key=self.query_one('#model_key',Input).value.strip()
            self.connecting=True
            self.query_one('#connect_model',Button).disabled=True
            self.query_one('#cancel_model',Button).disabled=True
            self.query_one('#error',Static).update('Testing a synthetic tool call…')
            self.connect(name,model,key)

    @work(thread=True,exclusive=True)
    def connect(self,name,model,key):
        from .setup import connect_model, save_model
        from .providers import ProviderError
        provider=None
        try:
            provider=connect_model(name,model,key)
            stored=save_model(self.root,provider)
        except Exception as exc:
            if provider:
                provider.close()
            message=str(exc) if isinstance(exc,ProviderError) else 'Connection setup could not be completed. Check the model settings and workspace access.'
            self.app.call_from_thread(self.failed,message)
            return
        self.app.call_from_thread(self.connected,provider,stored)

    def failed(self,message):
        self.connecting=False
        self.query_one('#model_key',Input).value=''
        self.query_one('#connect_model',Button).disabled=False
        self.query_one('#cancel_model',Button).disabled=False
        self.query_one('#error',Static).update(message)

    def connected(self,provider,stored):
        self.query_one('#model_key',Input).value=''
        self.dismiss((provider,stored))
