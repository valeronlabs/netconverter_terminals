"""Textual customer renderer. Detailed results never become model context."""

import json
from textual.app import App, ComposeResult
from textual.widgets import (
    Footer,
    Input,
    RichLog,
    Static,
    ProgressBar,
    DataTable,
    Button,
)
from textual import work
from textual.theme import Theme
from rich.text import Text
from .branding import banner
from textual.containers import Horizontal
import shlex
from .commands import execute, HELP
from .api import APIError


class Terminal(App):
    TITLE = "NetConverter · ASA → Palo Alto"
    CSS = """
    Screen { layout: vertical; background: #0a0a0b; color: #ececec; }
    #brand { height: auto; min-height: 5; max-height: 6; padding: 1 2; }
    #context { height: auto; min-height: 3; max-height: 5; padding: 0 2; color: #8b8b8d; }
    #conversation { height: 1fr; padding: 1 2; background: #0a0a0b; }
    #findings { height: 7; margin: 0 2; background: #141415; }
    #prompt { dock: bottom; margin: 0 2; border: tall #2a2a2c; background: #141415; }
    #prompt:focus { border: tall #3b82f6; }
    ProgressBar { height: 1; padding: 0 2; }
    #actions { height: 3; padding: 0 2; }
    #actions Button { min-width: 14; height: 3; margin-right: 1; border: tall #2a2a2c; background: #141415; }
    #actions Button:hover { background: #222224; border: tall #3b82f6; }
    #actions #open_config { color: #3b82f6; text-style: bold; }
    Footer { background: #141415; }
    """
    BINDINGS = [
        ("ctrl+q", "quit", "Quit"),
        ("ctrl+r", "refresh", "Refresh server status"),
    ]

    def __init__(self, controller):
        super().__init__()
        self.register_theme(Theme(name="netconverter", primary="#3b82f6", secondary="#06b6d4", accent="#3b82f6", foreground="#ececec", background="#0a0a0b", surface="#141415", panel="#1c1c1e", success="#22c55e", warning="#eab308", error="#ef4444", dark=True))
        self.theme = "netconverter"
        self.connected = False
        self.previous_job_status = None
        self.controller = controller
        self.busy = False
        self.downloaded_jobs = set()
        self.last_status = "not checked"

    def compose(self) -> ComposeResult:
        yield Static(banner(self.controller.workspace.root), id="brand")
        yield Static(id="context")
        yield ProgressBar(total=100, show_eta=False)
        with Horizontal(id="actions"):
            yield Button("Open config", id="open_config")
            yield Button("Analyze", id="analyze")
            yield Button("Convert", id="convert")
            yield Button("Download", id="download")
        yield RichLog(wrap=True, markup=False, id="conversation")
        yield DataTable(id="findings")
        yield Input(placeholder='Ask about your config, or type /help  ›', id="prompt")
        yield Footer()

    def on_mount(self):
        self.query_one(DataTable).add_columns("Field", "Value")
        self.query_one(DataTable).display = False
        self.query_one(ProgressBar).display = False
        self.query_one(RichLog).write(Text("Start with Open config → Convert → review your downloads.", style="bold #ececec"))
        self.query_one(RichLog).write(Text("Analyze ASA or Palo Alto configs for unused objects, routes, and traffic policy.\nUse /help for commands. Migration is limited to ASA → Palo Alto.", style="#8b8b8d"))
        self.render_context()
        self.query_one(Input).focus()
        self.run_command("/allowance")
        self.set_interval(3, self.poll)

    def render_context(self):
        c = self.controller
        p = c.provider
        model = f"{p.name}/{p.model}" if p else "guided commands (no model)"
        selected = c.state.get("selected", "none")
        metadata = c.state.get("configurations", {}).get(selected, {})
        label = metadata.get("display_name") or metadata.get("path") or selected
        remaining = c.allowance.get("remaining", {})
        allowance = " · ".join(f"{remaining[k]} {label}" for k, label in [("convert", "conversions"), ("analysis", "analyses"), ("query", "queries")] if k in remaining) or "checking allowance"
        context = Text()
        context.append("Server ", style="#8b8b8d")
        context.append("connected" if self.connected else "not connected", style="#22c55e" if self.connected else "#eab308")
        context.append("  ·  " + model + "  ·  " + allowance + "\n", style="#8b8b8d")
        context.append("Config ", style="#8b8b8d")
        context.append(str(label), style="#ececec")
        if c.state.get("active_job"):
            context.append("  ·  " + c.state["active_job"] + "  ·  " + self.last_status, style="#3b82f6")
        else:
            context.append("  ·  No active job", style="#8b8b8d")
        self.query_one("#context", Static).update(context)


    def on_input_submitted(self, event: Input.Submitted):
        if self.busy:
            return
        text = event.value
        event.input.value = ""
        if text.strip() == "/open":
            from .forms import OpenForm
            self.push_screen(OpenForm(self.controller.workspace.root), self.open_selected)
            return
        if text.strip() == "/convert":
            if not self.controller.allowance.get("targets"):
                self.query_one(RichLog).write(
                    "Run /allowance to load the server’s supported settings."
                )
                return
            from .forms import ConversionForm

            self.push_screen(
                ConversionForm(self.controller.allowance), self.submit_conversion
            )
            return
        # Do not retain the user's prompt/config snippets in transcript or on disk.
        self.run_command(text)

    def on_button_pressed(self, event):
        command = {"open_config": "/open", "analyze": "/analyze", "convert": "/convert", "download": "/download"}.get(event.button.id)
        if command and not self.busy:
            prompt = self.query_one("#prompt", Input)
            self.on_input_submitted(Input.Submitted(prompt, command))

    def open_selected(self, selection):
        if selection:
            self.last_status = "not checked"
            self.run_command("/open " + shlex.join(selection))

    @work(thread=True, exclusive=True, group="commands")
    def run_command(self, text):
        self.busy = True
        try:
            result = execute(self.controller, text)
        except APIError as exc:
            result = {"error": str(exc)}
            if exc.detail and isinstance(exc.detail, dict) and "fields" in exc.detail:
                result["required_decisions"] = exc.detail["fields"]
        except (ValueError, RuntimeError):
            result = {
                "error": "Command unavailable or invalid. Use /help and check the selected revision/provider."
            }
        except Exception:
            result = {
                "error": "Operation failed; originals and prior outputs are preserved."
            }
        finally:
            self.busy = False
        self.call_from_thread(self.show_result, result)

    def submit_conversion(self, options):
        if options is not None:
            self.run_command("/convert " + json.dumps(options))

    def show_result(self, result):
        if isinstance(result, list):
            result = {"jobs": result}
        log = self.query_one(RichLog)
        table = self.query_one(DataTable)
        table.clear()
        for key, value in result.get("details", result).items():
            table.add_row(str(key), json.dumps(value, default=str)[:500])
        table.display = "details" in result or "jobs" in result
        if "remaining" in result:
            self.connected = True
        elif "error" in result:
            log.write(Text(result["error"], style="#ef4444"))
            if "required_decisions" in result:
                log.write(Text("Required: " + ", ".join(result["required_decisions"]), style="#eab308"))
        elif "status" in result:
            state = (result.get("job_id"), result["status"], result.get("translation_status"))
            if state != self.previous_job_status:
                verdict = result.get("translation_status") or result["status"]
                color = "#eab308" if "warning" in verdict else "#22c55e" if result["status"] == "completed" else "#ef4444" if result["status"] == "failed" else "#3b82f6"
                log.write(Text(f"{result.get('job_id', '')}  {verdict.replace('_', ' ')}", style=color))
                self.previous_job_status = state
        elif "saved" in result:
            log.write(Text("Files saved · hashes verified", style="bold #22c55e"))
            for path in result["saved"]:
                log.write(Text("  " + path, style="#8b8b8d"))
        elif "configuration_id" in result and "bytes" in result:
            log.write(Text(f"Configuration selected · {result['bytes']:,} bytes · ready to analyze or convert", style="#3b82f6"))
        else:
            log.write(json.dumps(result, indent=2, default=str))
        if "status" in result:
            self.last_status = result["status"]
        if "progress" in result:
            self.query_one(ProgressBar).display = result.get("status") not in {"completed", "failed", "cancelled"}
            self.query_one(ProgressBar).update(progress=result["progress"])
        self.render_context()
        job = result.get("job_id")
        if result.get("requires_input") == "convert":
            from .forms import ConversionForm
            self.push_screen(ConversionForm(self.controller.allowance), self.submit_conversion)
        if result.get("status") == "completed" and job and job not in self.downloaded_jobs:
            self.downloaded_jobs.add(job)
            self.run_command("/download")

    def poll(self):
        if (
            not self.busy
            and self.controller.state.get("active_job")
            and self.last_status not in {"completed", "failed", "cancelled"}
        ):
            self.run_command("/status")

    def action_refresh(self):
        if not self.busy:
            self.run_command("/status")
