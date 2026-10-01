"""A compact command-first terminal; detailed data stays in the local renderer."""
import json
import shlex
from pathlib import Path
from .branding import banner
from rich.console import Group
from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Input, RichLog, Static, ProgressBar, Button, Footer
from textual.theme import Theme
from .commands import execute
from .api import APIError
from .workspace import WorkspaceError
from .providers import ProviderError
from .presentation import literal, heading, help_view, details_view, jobs_view, BLUE, MUTED


class Terminal(App):
    TITLE = 'NetConverter · ASA → Palo Alto'
    ENABLE_COMMAND_PALETTE = False
    CSS = '''
    Screen { layout: vertical; background: #0a0a0b; color: #ececec; }
    #brand { height: auto; padding: 1 2; border-bottom: solid #2a2a2c; }
    #context { text-wrap: nowrap; text-overflow: ellipsis; height: auto; min-height: 2; margin: 0 2; padding: 0 0 1 0; border-bottom: solid #2a2a2c; }
    #welcome { height: 1fr; margin: 1 2 0 2; overflow-y: auto; }
    #welcome Static { height: auto; margin-bottom: 1; }
    #welcome Button { height: 1; width: 100%; padding: 0; border: none; background: #0a0a0b; color: #3b82f6; content-align: left middle; text-align: left; }
    #welcome Button:hover, #welcome Button:focus { background: #1c1c1e; }
    #start { margin-bottom: 1; text-style: bold; }
    #navigation { height: 1; margin: 0 2 1 2; }
    #navigation Button { height: 1; min-width: 10; width: auto; margin-right: 2; padding: 0; border: none; background: #0a0a0b; color: #3b82f6; }
    #navigation Button:hover, #navigation Button:focus { background: #1c1c1e; }
    #job_progress { height: auto; margin: 0 2 1 2; color: #8b8b8d; }
    Screen.compact #brand { padding: 0 2; }
    Screen.compact #context { padding-bottom: 0; }
    Screen.compact #composer { height: 5; }
    Screen.compact #welcome { margin: 0 2; }
    Screen.compact #welcome Static { margin-bottom: 0; }
    Screen.compact #start { margin-bottom: 0; }
    #conversation { height: 1fr; margin: 0 2; background: #0a0a0b; scrollbar-size: 1 1; }
    #composer { height: 6; margin: 0 2; }
    #activity { height: 2; border-top: solid #2a2a2c; color: #8b8b8d; text-overflow: ellipsis; text-wrap: nowrap; }
    #prompt { height: 3; padding: 0 1; border: solid #2a2a2c; background: #141415; }
    #prompt:focus { border: solid #3b82f6; }
    ProgressBar { height: 1; }
    .muted { color: #8b8b8d; }
    Footer { background: #0a0a0b; color: #8b8b8d; }
    '''
    BINDINGS = [('ctrl+q','quit','Quit'),('ctrl+o','open','Open'),('ctrl+r','refresh','Status'),('f1','help','Help')]

    def __init__(self,controller):
        super().__init__()
        self.register_theme(Theme(name='netconverter',primary='#3b82f6',secondary='#3b82f6',accent='#3b82f6',foreground='#ececec',background='#0a0a0b',surface='#141415',panel='#1c1c1e',success='#22c55e',warning='#eab308',error='#ef4444',dark=True))
        self.theme='netconverter'
        self.controller=controller
        self.connected=False
        self.busy=False
        self.previous_job_status=None
        self.downloaded_jobs=set()
        self.last_status='not checked'
        self.next_after_open=None
        self.connection_error=False
        self.allowance_stale=False

    def compose(self)->ComposeResult:
        yield Static(banner(self.controller.workspace.root),id='brand')
        yield Static(id='context')
        with Vertical(id='welcome'):
            yield Static('Welcome. Open a configuration to begin.')
            yield Static('Selected files go directly to NetConverter. Automatic model requests contain restricted intent; configuration contents stay out of model context.', classes='muted',id='privacy_hint')
            yield Button('→ /open — choose a configuration to start',id='start')
            yield Static('Commands', classes='muted')
            for command,description,identifier in [
                ('/open','open config','open_config'),('/convert','convert ASA → Palo Alto','convert'),
                ('/analyze','analyze unused objects, routes, policy','analyze'),('/model','connect model','model'),
                ('/jobs','view jobs','jobs'),('/help','show all commands','help')]:
                label=Text(f'{command:12}',style=BLUE)
                label.append(description,style=MUTED)
                yield Button(label,id=identifier)
        yield Static('',id='job_progress',markup=False)
        yield RichLog(wrap=True,markup=False,highlight=False,min_width=1,max_lines=3000,id='conversation')
        with Horizontal(id='navigation'):
            yield Button('/open',id='nav_open')
            yield Button('/convert',id='nav_convert')
            yield Button('/jobs',id='nav_jobs')
            yield Button('/home',id='nav_home')
        with Vertical(id='composer'):
            yield Static('',id='activity')
            yield Input(placeholder='›  /open to begin · /help for commands',id='prompt')
            yield ProgressBar(total=100,show_eta=False)
        yield Footer()

    def on_mount(self):
        self.query_one(ProgressBar).display=False
        self.query_one('#job_progress').display=False
        self.welcome()
        self.resize_layout()
        self.render_context()
        self.query_one('#prompt',Input).focus()
        self.dispatch('/allowance',quiet=True)
        self.set_interval(3,self.poll)

    def on_resize(self):
        if self.is_mounted:
            self.resize_layout()

    def resize_layout(self):
        compact=self.size.height<32 or self.size.width<100
        self.screen.set_class(compact,'compact')
        self.query_one('#brand',Static).update(banner(self.controller.workspace.root,compact,self.size.width))
        self.query_one('#privacy_hint',Static).update('Files → NetConverter · restricted intent → model' if compact else 'Selected files go directly to NetConverter. Automatic model requests contain restricted intent; configuration contents stay out of model context.')

    def welcome(self):
        self.query_one('#welcome').display=True
        self.query_one('#conversation').display=False
        self.query_one('#navigation').display=False
        self.query_one('#job_progress').display=False

    def show_conversation(self):
        self.query_one('#welcome').display=False
        self.query_one('#conversation').display=True
        self.query_one('#navigation').display=True

    def render_context(self):
        c=self.controller
        provider=c.provider
        remaining=c.allowance.get('remaining',{})
        text=Text('Server ',style='#ececec')
        text.append('unavailable · retry /allowance' if self.connection_error else 'connected' if self.connected else 'checking connection',style='#22c55e' if self.connected and not self.connection_error else '#eab308')
        text.append('  ·  Model ',style='#ececec')
        text.append(literal(provider.name+' / '+provider.model if provider else 'not connected — /model to connect',MUTED if provider else '#eab308'))
        if remaining:
            text.append('\nLast known allowance  ' if self.allowance_stale else '\nRemaining today  ',style=MUTED)
            text.append('  ·  '.join(f'{remaining[k]} {label}' for k,label in [('convert','conversions'),('analysis','analyses'),('query','queries')] if k in remaining),style=MUTED)
        self.query_one('#context',Static).update(text)
        selected=c.state.get('selected')
        metadata=c.state.get('configurations',{}).get(selected,{})
        source=metadata.get('display_name') or metadata.get('path') or 'No configuration selected'
        job=c.state.get('active_job')
        status='Working…' if self.busy else (self.last_status.replace('_',' ') if job else 'Ready')
        self.query_one('#activity',Static).update(literal(f'{job+"  ·  " if job else ""}{status}  ·  {source}',MUTED))
        self.query_one('#prompt',Input).placeholder='›  Ask about this configuration, or /help' if provider else '›  Type /open to begin, or /help'

    def on_input_submitted(self,event:Input.Submitted):
        if self.busy:
            return
        text=event.value.strip()
        event.input.value=''
        if text:
            self.dispatch(text)

    def dispatch(self,text,quiet=False):
        if self.busy:
            return
        from .forms import OpenForm,ConversionForm,ModelForm
        if text in {'/clear','/home'}:
            if text=='/clear':
                self.query_one(RichLog).clear()
            self.welcome()
            return
        if text=='/help':
            self.show_conversation()
            self.query_one(RichLog).write(help_view())
            return
        if text=='/open':
            self.push_screen(OpenForm(self.controller.workspace.root),self.open_selected)
            return
        if text=='/model':
            self.push_screen(ModelForm(self.controller.workspace.root,self.controller.provider),self.model_selected)
            return
        if text=='/convert':
            if not self.controller.state.get('selected'):
                self.show_error('Choose a configuration first: /open.')
            elif not self.controller.allowance.get('targets'):
                self.show_error('Use /allowance to load the server’s conversion settings, then /convert.')
            else:
                self.push_screen(ConversionForm(self.controller.allowance),self.submit_conversion)
            return
        if text in {'/flow','/dependencies'}:
            self.show_conversation()
            example='/flow {"source_ip":"192.0.2.10","destination_ip":"198.51.100.10","protocol":"tcp","destination_port":80}' if text=='/flow' else '/dependencies {"object_name":"NAME"}'
            self.query_one(RichLog).write(heading('Enter explicit parameters',Group(literal(example),literal('These values go directly to NetConverter, never to the model.',MUTED))))
            return
        if not text.startswith('/') and not self.controller.provider:
            self.show_error('Connect a model with /model to ask questions, or use /help for guided commands.')
            return
        self.busy=True
        if text.startswith('/open '):
            self.update_progress('Uploading the selected file directly to NetConverter…')
        elif text.split(' ',1)[0] in {'/convert','/analyze','/optimize'}:
            self.update_progress('Submitting job · waiting for the server job ID…')
        elif text=='/download':
            self.update_progress('Downloading artifacts · verifying SHA-256 hashes…')
        if not quiet:
            self.show_conversation()
        self.render_context()
        self.run_command(text,quiet)

    def on_button_pressed(self,event):
        command={'start':'/open','nav_open':'/open','nav_convert':'/convert','nav_jobs':'/jobs','nav_home':'/home','open_config':'/open','analyze':'/analyze','convert':'/convert','jobs':'/jobs','model':'/model','help':'/help'}.get(event.button.id)
        if command:
            self.dispatch(command)

    def open_selected(self,selection):
        if selection:
            self.last_status='not checked'
            self.next_after_open=selection[2] if len(selection)>2 else None
            self.dispatch('/open '+shlex.join(selection[:2]))

    def submit_conversion(self,options):
        if options is not None:
            self.last_status='not checked'
            self.dispatch('/convert '+json.dumps(options))

    def model_selected(self,result):
        if result is None: # Cancel returns None; disabling is an explicit tuple.
            return
        provider,stored=result
        old=self.controller.provider
        self.controller.provider=provider
        if old and old is not provider:
            old.close()
        message='Model connected: '+provider.name+' / '+provider.model if provider else 'Guided commands selected.'
        if not stored:
            message+=' Key held in memory only for this session.'
        self.show_conversation()
        self.query_one(RichLog).write(heading('Model connection',literal(message)))
        self.render_context()
        self.query_one('#prompt',Input).focus()

    @work(thread=True,exclusive=True,group='commands')
    def run_command(self,text,quiet=False):
        try:
            result=execute(self.controller,text)
            if text.split(' ',1)[0] in {'/convert','/analyze','/optimize'}:
                try:
                    self.controller.capabilities()
                    self.allowance_stale=False
                except APIError:
                    self.allowance_stale=True
            self.connection_error=False
        except ProviderError as exc:
            result={'error':str(exc)+' Use /model to retry.'}
        except WorkspaceError as exc:
            result={'error':str(exc)}
        except APIError as exc:
            self.connection_error=exc.status in {0,401,403} or exc.status>=500
            messages={401:'Server key was rejected. Exit and run netconverter login.',403:'This key lacks terminal enrollment or permission. Contact NetConverter.',413:'The configuration exceeds the 50,000-byte pilot limit.',422:'Review the required conversion choices.',429:'An allowance or active-job limit was reached. Check /jobs and /allowance.',0:'Connection interrupted. Use /resume to recover a pending submission.'}
            result={'error':messages.get(exc.status,f'Server request failed (HTTP {exc.status}). Retry or contact NetConverter with the job ID.')}
        except (ValueError,RuntimeError):
            result={'error':'Check the command and its parameters. /help shows the supported commands.'}
        except Exception:
            result={'error':'The operation failed. Your original configuration and prior outputs are preserved.'}
        self.call_from_thread(self.finish_command,result,text,quiet)

    def finish_command(self,result,text,quiet):
        self.busy=False
        if isinstance(result,dict) and 'error' in result:
            self.update_progress('Action needed · see the message below.')
        self.show_result(result,quiet=quiet)
        self.render_context()
        if text.startswith('/open '):
            following=self.next_after_open
            self.next_after_open=None
            if following and 'configuration_id' in result:
                self.dispatch('/'+following)

    def update_progress(self,message):
        view=self.query_one('#job_progress',Static)
        view.update(literal(message))
        view.display=True

    def show_error(self,message):
        self.show_conversation()
        self.query_one(RichLog).write(heading('Next step',literal(message,'#eab308')))

    def show_result(self,result,quiet=False):
        log=self.query_one(RichLog)
        if not quiet or 'status' in result or 'saved' in result:
            self.show_conversation()
        if isinstance(result,list):
            result={'jobs':result}
        if 'remaining' in result:
            self.connected=True
            self.connection_error=False
            self.allowance_stale=False
            if not quiet:
                log.write(heading('Remaining today',details_view(result['remaining'])))
        elif 'error' in result:
            self.show_error(result['error'])
        elif 'help' in result:
            log.write(help_view())
        elif 'jobs' in result:
            log.write(heading('Server jobs',jobs_view(result['jobs'],self.controller.state,compact=self.size.width<110)))
        elif 'details' in result:
            if result.get('coverage'):
                log.write(heading('Coverage',literal(result['coverage'],MUTED)))
            log.write(heading('Findings',details_view(result['details'])))
            if result.get('saved'):
                log.write(heading('Complete findings saved',Group(*(literal(str(Path(p).name),MUTED) for p in result['saved']))))
        elif 'status' in result:
            verdict=result.get('translation_status') or result['status']
            percent=result.get('progress')
            progress=f' · {percent:g}%' if isinstance(percent,(int,float)) else ''
            self.update_progress(f"Job {result.get('job_id','—')} · {verdict.replace('_',' ')}{progress}")
            state=(result.get('job_id'),result['status'],result.get('translation_status'))
            if state!=self.previous_job_status:
                verdict=result.get('translation_status') or result['status']
                log.write(heading(result.get('job_id','Server job'),literal(verdict.replace('_',' '),'#ef4444' if result['status']=='failed' else '#eab308' if 'warning' in verdict or result['status']!='completed' else '#22c55e')))
                self.previous_job_status=state
        elif 'saved' in result:
            self.update_progress(f"Job {result.get('job_id','—')} · downloads verified")
            from .presentation import artifacts_view
            log.write(heading('Downloaded · SHA-256 hashes verified',artifacts_view(result['saved'])))
            log.write(literal('Open these local files in your preferred editor or spreadsheet application.\n',MUTED))
        elif 'configuration_id' in result:
            self.query_one('#job_progress').display=False
            log.write(heading('Configuration selected',literal('Upload verified · /convert to migrate · /analyze to inspect' if 'parent_job_id' not in result else 'Generated target selected. Run /analyze before asking questions.')))
        elif 'requires_input' in result:
            operation=result['requires_input']
            self.dispatch('/'+operation)
        else:
            log.write(heading('Result',details_view(result)))
        if 'status' in result:
            self.last_status=result['status']
        if 'progress' in result and isinstance(result['progress'],(int,float)):
            self.query_one(ProgressBar).display=result.get('status') not in {'completed','failed','cancelled'}
            self.query_one(ProgressBar).update(progress=max(0,min(100,result['progress'])))
        self.render_context()
        job=result.get('job_id')
        if 'saved' in result and job:
            self.downloaded_jobs.add(job)
        if result.get('status')=='completed' and job and job not in self.downloaded_jobs:
            self.dispatch('/download',quiet=True)

    def poll(self):
        if len(self.screen_stack)==1 and not self.busy and self.controller.state.get('active_job') and self.last_status not in {'completed','failed','cancelled'}:
            self.dispatch('/status',quiet=True)

    def action_refresh(self):
        self.dispatch('/status')

    def action_open(self):
        self.dispatch('/open')

    def action_help(self):
        self.dispatch('/help')

    def on_unmount(self):
        if self.controller.provider:
            self.controller.provider.close()
