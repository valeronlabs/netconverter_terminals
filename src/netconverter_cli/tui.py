"""A compact command-first terminal; detailed data stays in the local renderer."""
import json
import shlex
from pathlib import Path

from rich.console import Group
from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.containers import Vertical
from textual.theme import Theme
from textual.widgets import Footer, Input, OptionList, RichLog, Static

from . import activity
from .api import APIError
from .branding import header
from .catalog import label
from .commands import execute
from .palette import ACCENT, BG, BORDER, DIM, ERROR, FG, MUTED, PANEL, SUCCESS, SURFACE, WARNING
from .presentation import (activity_line, activity_view, ago, artifacts_view, badge, card,
                           commands_table, details_view, help_view, jobs_view, literal)
from .providers import ProviderError
from .workspace import WorkspaceError

SPINNER = '⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏'
FINAL = {'completed', 'failed', 'cancelled'}
SUBMIT_COMMANDS = {'/convert', '/validate', '/analyze', '/optimize'}


class Terminal(App):
    TITLE = 'NetConverter CLI'
    ENABLE_COMMAND_PALETTE = False
    CSS = f"""
    Screen {{ layout: vertical; background: {BG}; color: {FG}; }}
    #header {{ height: 1; padding: 0 2; background: {SURFACE}; }}
    #conversation {{ height: 1fr; margin: 1 1 0 1; padding: 0 1; background: {BG}; scrollbar-size: 1 1;
                     overflow-x: hidden;
                     scrollbar-color: {BORDER}; scrollbar-background: {BG}; }}
    #ask {{ height: auto; margin: 0 1; padding: 0 1; border: round {ACCENT}; border-title-color: {FG};
            border-title-style: bold; border-subtitle-color: {MUTED}; background: {BG}; }}
    #choices {{ height: auto; max-height: 10; padding: 0; border: none; background: {BG}; color: {FG};
                scrollbar-size: 1 1; }}
    #choices:focus {{ background-tint: transparent; }}
    #choices > .option-list--option {{ padding: 0 1; }}
    #choices > .option-list--option-highlighted, #choices:focus > .option-list--option-highlighted {{
        background: {PANEL}; color: {FG}; text-style: bold; }}
    #status {{ height: 1; margin: 0 2; color: {MUTED}; text-wrap: nowrap; text-overflow: ellipsis; }}
    #prompt {{ height: 3; margin: 0 1; padding: 0 1; border: round {BORDER}; background: {BG};
               border-title-color: {FG}; border-subtitle-color: {MUTED}; }}
    #prompt:focus {{ border: round {ACCENT}; background-tint: transparent; }}
    Footer {{ background: {SURFACE}; color: {MUTED}; }}
    """
    BINDINGS = [('ctrl+q', 'quit', 'Quit'), ('ctrl+o', 'open', 'Open'), ('ctrl+r', 'refresh', 'Status'),
                ('ctrl+j', 'jobs', 'Jobs'), ('escape', 'cancel_input', 'Cancel'), ('f1', 'help', 'Help')]

    def __init__(self, controller):
        super().__init__()
        self.register_theme(Theme(name='netconverter', primary=ACCENT, secondary=ACCENT, accent=ACCENT,
                                  foreground=FG, background=BG, surface=SURFACE, panel=PANEL,
                                  success=SUCCESS, warning=WARNING, error=ERROR, dark=True))
        self.theme = 'netconverter'
        self.controller = controller
        self.connected = False
        self.busy = False
        self.busy_label = ''
        self.previous_job_status = None
        self.downloaded_jobs = set()
        self.last_status = 'not checked'
        self.last_progress = None
        self.next_after_open = None
        self.connection_error = False
        self.allowance_stale = False
        self.answer_callback = None
        self.choice_values = []
        self.choice_labels = []
        self.text_answer = False
        self.after_catalog = None
        self.spin = 0
        self.bridge_seen = activity.mtime(self.controller.workspace.state_dir)
        from .guided import Guided
        self.guided = Guided(self)

    def compose(self) -> ComposeResult:
        yield Static(id='header')
        yield RichLog(wrap=True, markup=False, highlight=False, min_width=1, max_lines=3000, id='conversation')
        with Vertical(id='ask'):
            yield OptionList(id='choices', markup=False, compact=True)
        yield Static('', id='status', markup=False)
        yield Input(placeholder='Type / for commands', id='prompt', compact=True)
        yield Footer()

    def on_mount(self):
        self.clear_question()
        self.welcome()
        self.render_context()
        self.dispatch('/allowance', quiet=True)
        self.set_interval(3, self.poll)
        self.set_interval(0.12, self.tick)

    def on_resize(self):
        if self.is_mounted:
            self.query_one('#choices').styles.max_height = 6 if self.size.height < 30 else 10
            self.render_context()

    # -- conversation ----------------------------------------------------------

    def write(self, renderable):
        self.query_one(RichLog).write(renderable, expand=True)

    def write_note(self, message):
        self.write(literal(message, MUTED))

    def welcome(self):
        rows = [('/convert', 'Migrate a configuration to another vendor'),
                ('/validate', 'Check a configuration before migrating'),
                ('/optimize', 'Cleanup and optimization findings'),
                ('/jobs', 'Your server jobs'),
                ('/activity', 'What your AI assistant did here'),
                ('/help', 'Every command')]
        self.write(card('Start', Group(commands_table(rows), Text(''),
                                       literal('Your AI can drive this too: /connect wires Claude Code, Claude Desktop, Cursor, '
                                               'VS Code or Codex to this folder. Configurations go straight to '
                                               'NetConverter; the AI sees paths and summaries.', MUTED))))

    def folder_command(self, command, argument):
        from .presentation import folder_view
        from .workspace import WorkspaceError
        try:
            if command == '/cd':
                result = self.controller.change_folder(argument)
                self.render_context()
                jobs = result['jobs_here']
                self.write_note(f"Now working in {result['folder']}"
                                + (f" · {jobs} job(s) remembered here" if jobs else ''))
                self.write(folder_view(self.controller.list_folder('')))
            elif command == '/pwd':
                self.write_note(str(self.controller.workspace.root))
            else:
                self.write(folder_view(self.controller.list_folder(argument)))
        except (WorkspaceError, OSError) as exc:
            self.show_error(str(exc))

    def show_error(self, message):
        self.write(card('Next step', literal(message, FG), 'warning'))

    # -- questions -------------------------------------------------------------

    def clear_question(self):
        self.answer_callback = None
        self.choice_values = []
        self.choice_labels = []
        self.text_answer = False
        self.query_one('#ask').display = False
        field = self.query_one('#prompt', Input)
        field.password = False
        field.value = ''
        field.disabled = False
        field.display = True
        field.border_title = ''
        field.border_subtitle = ''
        self.query_one('#status').display = True
        field.focus()
        self.refresh_bindings()

    def _option(self, index, text, marked):
        prompt = Text('▸ ' if marked else '  ', style=ACCENT)
        prompt.append(f'{index + 1:>2}  ' if index < 9 else '    ', style=MUTED)
        prompt.append(literal(text))
        return prompt

    def ask_choice(self, title, choices, callback, highlight=0):
        self.clear_question()
        self.answer_callback = callback
        self.choice_values = choices
        self.choice_labels = [str(label_) for label_, _ in choices]
        box = self.query_one('#ask')
        box.border_title = title
        box.border_subtitle = '↑↓ choose · 1–9 jump · Enter · Esc cancel'
        options = self.query_one('#choices', OptionList)
        options.clear_options()
        options.add_options([self._option(i, text, i == highlight) for i, text in enumerate(self.choice_labels)])
        options.highlighted = min(max(highlight, 0), len(choices) - 1)
        box.display = True
        self.query_one('#prompt', Input).display = False
        self.query_one('#status').display = False
        options.focus()
        self.refresh_bindings()

    @property
    def question(self):
        """The open question's title, for tests and screen readers."""
        if self.answer_callback is None:
            return ''
        return str((self.query_one('#prompt') if self.text_answer else self.query_one('#ask')).border_title)

    def on_option_list_option_highlighted(self, event):
        if event.option_list.id != 'choices' or not self.choice_labels:
            return
        for index, text in enumerate(self.choice_labels):
            event.option_list.replace_option_prompt_at_index(index, self._option(index, text, index == event.option_index))

    def ask_text(self, title, callback, secret=False, hint=''):
        self.clear_question()
        self.answer_callback = callback
        self.text_answer = True
        field = self.query_one('#prompt', Input)
        field.border_title = title
        field.border_subtitle = hint or 'Enter continue · Esc cancel'
        field.password = secret
        field.placeholder = 'Hidden · Enter to continue' if secret else 'Type a value'
        field.focus()
        self.refresh_bindings()

    def on_key(self, event):
        if (self.answer_callback and not self.text_answer and not self.busy
                and event.character and event.character.isdigit() and event.character != '0'):
            index = int(event.character) - 1
            if index < len(self.choice_values):
                event.stop()
                self.choose_index(index)

    def choose_index(self, index):
        callback = self.answer_callback
        text, value = self.choice_values[index]
        self.clear_question()
        self.write_note('› ' + str(text))
        callback(value)

    def on_option_list_option_selected(self, event):
        if self.answer_callback and not self.text_answer and not self.busy:
            self.choose_index(event.option_index)

    def action_cancel_input(self):
        if self.answer_callback and not self.busy:
            self.clear_question()
            self.write_note('Cancelled. Nothing was submitted.')
            self.render_context()

    def check_action(self, action, parameters):
        if action == 'cancel_input':
            return True if self.answer_callback else False  # hidden, not dimmed
        if action in {'open', 'refresh', 'jobs'}:
            return None if self.answer_callback else True
        return True

    # -- header and status -------------------------------------------------------

    def bridge_state(self):
        entries = activity.recent(self.controller.workspace.state_dir, 1)
        if not entries:
            return None
        return (entries[-1].get('client') or 'AI', ago(entries[-1].get('ts')))

    def render_context(self):
        c = self.controller
        provider = c.provider
        catalog = c.catalog
        server = 'offline' if self.connection_error else 'connected' if self.connected else 'checking'
        profile = catalog.describe() if self.size.width >= 110 else ('pilot' if catalog.profile == 'quick' else '')
        remaining = c.allowance.get('remaining') or {}
        allowance = ''
        if 'convert' in remaining:
            left = remaining['convert']
            allowance = ('Unlimited' if left is None else str(left)) + ' conversions left' + (' (last known)' if self.allowance_stale else '')
        model = f'{provider.name}/{provider.model}' if provider else None
        self.query_one('#header', Static).update(header(self.size.width or 80, server=server, profile=profile,
                                                        bridge=self.bridge_state(), model=model, allowance=allowance))
        self.render_status()
        if not self.answer_callback:
            self.query_one('#prompt', Input).placeholder = (
                'Ask about the active job, or type / for commands' if provider else
                'Type a command — /convert  /validate  /jobs  /help')

    def render_status(self):
        c = self.controller
        selected = c.state.get('selected')
        metadata = c.state.get('configurations', {}).get(selected, {})
        source = metadata.get('display_name') or metadata.get('path')
        job = c.state.get('active_job')
        text = Text()
        if self.busy:
            text.append(SPINNER[self.spin % len(SPINNER)] + ' ', style=ACCENT)
            text.append((self.busy_label or 'Working…') + '  ', style=FG)
        if job:
            text.append(job, style=ACCENT)
            if not self.busy:
                status = self.last_status if self.last_status != 'not checked' else 'submitted'
                text.append('  ' + status.replace('_', ' '), style=FG)
                if isinstance(self.last_progress, (int, float)) and status not in FINAL:
                    filled = int(max(0, min(100, self.last_progress)) / 10)
                    text.append(f'  {self.last_progress:g}% ', style=MUTED)
                    text.append('█' * filled, style=ACCENT)
                    text.append('░' * (10 - filled), style=DIM)
        if source:
            text.append(('  ·  ' if text.plain else '') + source, style=MUTED)
        if not text.plain:
            text.append('Ready', style=MUTED)
            text.append('  ·  ' + self.folder_name(), style=DIM)
        self.query_one('#status', Static).update(text)

    def folder_name(self):
        from .branding import folder_label
        return folder_label(self.controller.workspace.root)

    def tick(self):
        if self.busy:
            self.spin += 1
            self.render_status()

    def set_busy(self, busy, label_=''):
        self.busy = busy
        self.busy_label = label_
        self.render_status()

    # -- commands ----------------------------------------------------------------

    def on_input_submitted(self, event: Input.Submitted):
        if self.busy:
            return
        text = event.value.strip()
        event.input.value = ''
        if self.answer_callback and self.text_answer:
            callback = self.answer_callback
            secret = event.input.password
            self.clear_question()
            if text and not secret:
                self.write_note('› ' + text)
            callback(text)
        elif text:
            # Never echo arbitrary free text or credentials into conversation history.
            self.dispatch(text)

    def dispatch(self, text, quiet=False):
        if self.busy or self.answer_callback:
            return
        command = text.split(' ', 1)[0]
        if text in {'/clear', '/home'}:
            if text == '/clear':
                self.query_one(RichLog).clear()
            self.welcome()
            return
        if text == '/help':
            self.write(help_view())
            return
        if command in {'/cd', '/ls', '/dir', '/pwd'}:
            self.folder_command(command, text[len(command):].strip())
            return
        if text == '/activity':
            entries = activity.recent(self.controller.workspace.state_dir, 20)
            self.write(card('Bridge activity', activity_view(entries)))
            return
        if text == '/connect':
            self.guided.connect()
            return
        if text == '/open':
            self.guided.open()
            return
        if text == '/model':
            self.guided.model()
            return
        if text in {'/convert', '/validate', '/analyze', '/optimize'}:
            self.guided.start({'/analyze': 'validate'}.get(text, text[1:]))
            return
        if text in {'/flow', '/dependencies'}:
            example = ('/flow {"source_ip":"192.0.2.10","destination_ip":"198.51.100.10","protocol":"tcp","destination_port":80}'
                       if text == '/flow' else '/dependencies {"object_name":"NAME"}')
            self.write(card('Enter explicit parameters', Group(literal(example),
                       literal('These values go directly to NetConverter, never to the model.', MUTED))))
            return
        if not text.startswith('/') and not self.controller.provider:
            self.show_error('Plain-language questions need a model: /model connects one. '
                            'Or ask your own AI assistant after /connect.')
            return
        label_ = 'Working…'
        if command == '/open':
            label_ = 'Preparing the selected file…' if self.controller.external else 'Uploading directly to NetConverter…'
        elif command in SUBMIT_COMMANDS:
            label_ = 'Submitting · waiting for the job ID…'
        elif command == '/download':
            label_ = 'Downloading · verifying SHA-256…'
        elif command == '/allowance':
            label_ = 'Connecting to NetConverter…'
        self.set_busy(True, label_)
        self.render_context()
        self.run_command(text, quiet)

    def load_catalog(self, following):
        self.after_catalog = following
        self.dispatch('/allowance', quiet=True)

    def open_selected(self, selection):
        if selection:
            self.last_status = 'not checked'
            self.next_after_open = selection[2] if len(selection) > 2 else None
            self.dispatch('/open ' + shlex.join(selection[:2]))

    def submit_job(self, job_type, options):
        self.last_status = 'not checked'
        self.last_progress = None
        # Always with an options object: a bare /validate opens the guided flow instead.
        self.dispatch(f'/{job_type} ' + json.dumps(options or {}))

    def submit_conversion(self, options):  # 0.1.x name
        if options is not None:
            self.submit_job('convert', options)

    def apply_connect(self, change):
        try:
            message = change.apply()
        except Exception as exc:
            self.show_error(f'Could not apply: {str(exc)[:300]}')
            return
        from .connect import CLIENTS
        done = 'connected' if change.key in CLIENTS else 'applied'
        self.write(card(f'{change.title} {done}', literal(message), 'success'))
        for extra in change.followups:  # e.g. the Claude Code read rule, offered with its own prompt
            self.guided.connect_review(extra)

    def model_selected(self, result):
        if result is None:  # Cancel returns None; disabling is an explicit tuple.
            return
        provider, stored = result
        old = self.controller.provider
        self.controller.provider = provider
        if old and old is not provider:
            old.close()
        message = 'Model connected: ' + provider.name + ' / ' + provider.model if provider else 'Guided commands selected.'
        if not stored:
            message += ' Key held in memory only for this session.'
        self.write(card('Model connection', literal(message), 'success' if provider else 'info'))
        self.render_context()
        self.query_one('#prompt', Input).focus()

    def connect_model_inline(self, name, model, key):
        self.set_busy(True, 'Testing a synthetic model tool call…')
        self.test_model(name, model, key)

    @work(thread=True, exclusive=True, group='model')
    def test_model(self, name, model, key):
        from .setup import connect_model, save_model
        provider = None
        try:
            provider = connect_model(name, model, key)
            stored = save_model(self.controller.workspace.root, provider)
        except Exception as exc:
            if provider:
                provider.close()
            message = str(exc) if isinstance(exc, ProviderError) else 'Model setup could not be completed. Check settings and workspace access.'
            self.call_from_thread(self.model_failed, message)
            return
        self.call_from_thread(self.model_connected, provider, stored)

    def model_failed(self, message):
        self.set_busy(False)
        self.show_error(message)
        self.ask_choice('Model connection', [('Retry model setup', True), ('Keep current connection / guided commands', False)],
                        lambda retry: self.guided.model() if retry else self.render_context())

    def model_connected(self, provider, stored):
        self.set_busy(False)
        self.model_selected((provider, stored))

    @work(thread=True, exclusive=True, group='commands')
    def run_command(self, text, quiet=False):
        try:
            result = execute(self.controller, text)
            if text.split(' ', 1)[0] in SUBMIT_COMMANDS:
                try:
                    self.controller.capabilities()
                    self.allowance_stale = False
                except APIError:
                    self.allowance_stale = True
            self.connection_error = False
        except ProviderError as exc:
            result = {'error': str(exc) + ' Use /model to retry.'}
        except WorkspaceError as exc:
            result = {'error': str(exc)}
        except APIError as exc:
            self.connection_error = exc.status in {0, 401, 403} or exc.status >= 500
            limit = f'{self.controller.max_bytes():,}'
            messages = {401: 'NetConverter did not accept your sign-in. Exit and run netconverter login.',
                        403: 'This credential lacks permission for that action. Contact NetConverter.',
                        413: f'The configuration exceeds your {limit}-byte limit.',
                        422: 'NetConverter could not accept these choices. Review them and retry.',
                        429: 'A usage or active-job limit was reached. Check /jobs and /allowance.',
                        0: 'Connection interrupted. /resume recovers a pending submission.'}
            result = {'error': messages.get(exc.status, f'Server request failed (HTTP {exc.status}). Retry, or contact NetConverter with the job ID.')}
        except (ValueError, RuntimeError):
            result = {'error': 'Check the command and its parameters. /help shows the supported commands.'}
        except Exception:
            result = {'error': 'The operation failed. Your original configuration and prior outputs are preserved.'}
        self.call_from_thread(self.finish_command, result, text, quiet)

    def finish_command(self, result, text, quiet):
        self.set_busy(False)
        self.show_result(result, quiet=quiet)
        self.render_context()
        if text == '/allowance' and self.after_catalog and self.controller.catalog.loaded:
            following, self.after_catalog = self.after_catalog, None
            following()
        if text.startswith('/open '):
            following = self.next_after_open
            self.next_after_open = None
            if following and isinstance(result, dict) and 'configuration_id' in result:
                self.guided.after_open(following)

    def show_result(self, result, quiet=False):
        if isinstance(result, list):
            result = {'jobs': result}
        if 'remaining' in result or 'vendors' in result:
            self.connected = True
            self.connection_error = False
            self.allowance_stale = False
            if not quiet:
                self.write(card('Server capabilities', self.capabilities_view(result)))
        elif 'error' in result:
            self.show_error(result['error'])
        elif 'help' in result:
            self.write(help_view())
        elif 'jobs' in result:
            self.write(card('Server jobs', jobs_view(result['jobs'], self.controller.state,
                                                     compact=self.size.width < 100, catalog=self.controller.catalog)))
        elif 'details' in result:
            if result.get('coverage'):
                self.write(card('Coverage', literal(result['coverage'], MUTED), 'muted'))
            self.write(card(label(result.get('operation', 'Findings')).replace('_', ' ').capitalize()
                            if result.get('operation') else 'Findings', details_view(result['details'])))
            if result.get('saved'):
                self.write(card('Complete findings saved', Group(*(literal(Path(p).name, MUTED) for p in result['saved'])), 'muted'))
        elif 'status' in result:
            self.show_job(result)
        elif 'saved' in result:
            self.write(card('Downloaded · SHA-256 verified', artifacts_view(result['saved']), 'success'))
        elif 'configuration_id' in result:
            if 'parent_job_id' in result:
                self.write(card('Generated configuration selected', literal('Run /validate to check it.'), 'success'))
            else:
                where = ('pinned by SHA-256; nothing is sent until you submit' if result.get('local')
                         else 'upload verified')
                if self.next_after_open:
                    self.write_note(f'✓ Configuration {where}.')
                else:
                    self.write(card('Configuration selected', literal(where.capitalize() + '. Next: /convert, /validate or /optimize.'), 'success'))
        elif 'requires_input' in result:
            self.dispatch('/' + result['requires_input'])
        else:
            self.write(card('Result', details_view(result)))
        self.render_context()
        job = result.get('job_id')
        if 'saved' in result and job:
            self.downloaded_jobs.add(job)
        if result.get('status') == 'completed' and job and job not in self.downloaded_jobs:
            self.dispatch('/download', quiet=True)

    def capabilities_view(self, result):
        catalog = self.controller.catalog
        rows = {}
        if catalog.profile == 'quick':
            rows['Credential'] = 'Pilot key · ASA → Palo Alto only'
            remaining = result.get('remaining') or {}
            for key, name in (('convert', 'Conversions left'), ('analysis', 'Analyses left'), ('query', 'Questions left')):
                if key in remaining:
                    rows[name] = 'Unlimited' if remaining[key] is None else remaining[key]
        else:
            rows['Credential'] = 'Trial' if catalog.trial else 'Full API'
            for kind in ('firewall', 'router', 'switch'):
                names = sorted({v['name'] for v in catalog.vendors.values()
                                if v['device_type'] == kind and 'source' in v['roles']})
                if names:
                    rows[kind.capitalize() + 's'] = ', '.join(names)
            rows['Jobs'] = ', '.join(label(t) for t in catalog.job_types)
        rows['File limit'] = f'{catalog.max_bytes:,} bytes'
        return details_view(rows)

    def show_job(self, result):
        verdict = result.get('translation_status') or result['status']
        self.last_status = result['status']
        self.last_progress = result.get('progress') if isinstance(result.get('progress'), (int, float)) else None
        state = (result.get('job_id'), result['status'], result.get('translation_status'))
        if state != self.previous_job_status:
            line = Text()
            line.append_text(badge(verdict))
            if result['status'] not in FINAL and verdict != result['status']:
                line.append('  ' + result['status'].replace('_', ' '), style=MUTED)
            if isinstance(result.get('progress'), (int, float)) and result['status'] not in FINAL:
                line.append(f"  {result['progress']:g}%", style=MUTED)
            kind = 'error' if result['status'] == 'failed' else 'success' if result['status'] == 'completed' else 'info'
            body = [line]
            for field in ('validation', 'optimization'):
                if isinstance(result.get(field), dict):
                    body.append(details_view(result[field]))
            for field in ('blocking_reasons', 'review_reasons'):
                if result.get(field):
                    body.append(literal(field.replace('_', ' ').capitalize() + ':', MUTED))
                    body.extend(literal('• ' + str(r), FG) for r in result[field][:5])
            self.write(card(f"Job {result.get('job_id', '')}", Group(*body), kind))
            self.previous_job_status = state

    def poll(self):
        if self.answer_callback or len(self.screen_stack) != 1 or self.busy:
            return
        seen = activity.mtime(self.controller.workspace.state_dir)
        if seen > self.bridge_seen:
            for entry in activity.recent(self.controller.workspace.state_dir, 5):
                if entry.get('ts', 0) > self.bridge_seen:
                    self.write(activity_line(entry))
            self.bridge_seen = seen
            self.render_context()
        if self.controller.state.get('active_job') and self.last_status not in FINAL:
            self.dispatch('/status', quiet=True)

    def action_refresh(self):
        self.dispatch('/status')

    def action_open(self):
        self.dispatch('/open')

    def action_jobs(self):
        self.dispatch('/jobs')

    def action_help(self):
        self.dispatch('/help')

    def on_unmount(self):
        if self.controller.provider:
            self.controller.provider.close()
        if getattr(self.controller, '_remote', None):
            self.controller._remote.close()
