"""A compact command-first terminal; detailed data stays in the local renderer."""
import json
import shlex
from pathlib import Path
from .branding import banner
from rich.console import Group
from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.containers import Vertical
from textual.widgets import Input, RichLog, Static, ProgressBar, OptionList, Footer
from textual.theme import Theme
from .commands import execute
from .api import APIError
from .workspace import WorkspaceError
from .providers import ProviderError
from .presentation import literal, heading, help_view, details_view, jobs_view, BLUE, MUTED


class Terminal(App):
    TITLE = 'NetConverter · ASA → Palo Alto'
    ENABLE_COMMAND_PALETTE = False
    CSS = """
    Screen { layout: vertical; background: #0a0a0b; color: #ececec; }
    #brand { height: auto; padding: 0 2; margin-top: 1; }
    #context { height: 2; margin: 1 2; text-wrap: nowrap; text-overflow: ellipsis; color: #8b8b8d; }
    #conversation { height: 1fr; margin: 0 2; background: #0a0a0b; scrollbar-size: 1 1; }
    #job_progress { height: auto; margin: 0 2; color: #8b8b8d; }
    #question { height: auto; margin: 1 2 0 2; color: #3b82f6; text-style: bold; }
    #choices { height: auto; max-height: 8; min-height: 1; margin: 0 2; padding: 0; border: none; background: #0a0a0b; scrollbar-size: 1 1; }
    #choices:focus { background-tint: transparent; }
    #choices > .option-list--option-highlighted, #choices:focus > .option-list--option-highlighted { background: #0a0a0b; color: #3b82f6; text-style: bold; }
    #choice_hint { height: auto; margin: 0 2; color: #8b8b8d; }
    #composer { height: auto; margin: 0 2; }
    #activity { height: 1; color: #8b8b8d; text-wrap: nowrap; text-overflow: ellipsis; }
    #prompt { height: 1; border: none; padding: 0; margin: 1 0; background: #0a0a0b; }
    ProgressBar { height: 1; }
    Footer { background: #0a0a0b; color: #8b8b8d; }
    """
    BINDINGS = [('ctrl+q','quit','Quit'),('ctrl+o','open','Open'),('ctrl+r','refresh','Status'),('escape','cancel_input','Cancel choice'),('f1','help','Help')]

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
        self.answer_callback=None
        self.choice_values=[]
        self.text_answer=False
        from .guided import Guided
        self.guided=Guided(self)

    def compose(self)->ComposeResult:
        yield Static(banner(self.controller.workspace.root,compact=True),id='brand')
        yield Static(id='context')
        yield Static('',id='job_progress',markup=False)
        yield RichLog(wrap=True,markup=False,highlight=False,min_width=1,max_lines=3000,id='conversation')
        yield Static('',id='question',markup=False)
        yield OptionList(id='choices',markup=False,compact=True)
        yield Static('',id='choice_hint',markup=False)
        with Vertical(id='composer'):
            yield Static('',id='activity')
            yield Input(placeholder='›  /convert to begin · /help for commands',id='prompt',compact=True)
            yield ProgressBar(total=100,show_eta=False)
        yield Footer()

    def on_mount(self):
        self.query_one(ProgressBar).display=False
        self.query_one('#job_progress').display=False
        self.clear_question()
        self.welcome()
        self.resize_layout()
        self.render_context()
        self.dispatch('/allowance',quiet=True)
        self.set_interval(3,self.poll)

    def on_resize(self):
        if self.is_mounted:
            self.resize_layout()

    def resize_layout(self):
        self.query_one('#brand',Static).update(banner(self.controller.workspace.root,True,self.size.width))
        self.query_one('#choices').styles.max_height=5 if self.size.height<32 else 8

    def welcome(self):
        self.query_one(RichLog).write(Group(
            literal('ASA → Palo Alto. Start with /convert.', 'bold'),
            literal('Choose with ↑ ↓ and Enter. Esc cancels a choice. No mouse needed.',MUTED),
            Text(''),
            literal('/convert   Select an ASA file and walk through migration settings',BLUE),
            literal('/open      Select a configuration for analysis',BLUE),
            literal('/analyze   Analyze the selected source or generated target',BLUE),
            literal('/model     Connect or repair your model',BLUE),
            literal('/jobs      Find a server job     /help  All commands',BLUE),
            Text(''),literal('Files go directly to NetConverter; model requests contain restricted intent.',MUTED),Text('')))

    def write_note(self,message):
        self.query_one(RichLog).write(literal(message,MUTED))

    def clear_question(self):
        self.answer_callback=None
        self.choice_values=[]
        self.text_answer=False
        for widget in ('#choices','#question','#choice_hint'):
            self.query_one(widget).display=False
        field=self.query_one('#prompt',Input)
        field.password=False
        field.value=''
        field.disabled=False
        field.display=True
        field.focus()

    def ask_choice(self,title,choices,callback):
        self.clear_question()
        self.answer_callback=callback
        self.choice_values=choices
        self.query_one('#question',Static).update(literal(title))
        options=self.query_one('#choices',OptionList)
        options.clear_options()
        options.add_options([literal(f"{i+1}. {label}") for i,(label,_) in enumerate(choices)])
        options.highlighted=0
        self.query_one('#choice_hint',Static).update('↑ ↓ choose · Enter continue · Esc cancel')
        for widget in ('#choices','#question','#choice_hint'):
            self.query_one(widget).display=True
        self.query_one('#prompt',Input).display=False
        options.focus()

    def ask_text(self,title,callback,secret=False,hint=''):
        self.clear_question()
        self.answer_callback=callback
        self.text_answer=True
        self.query_one('#question',Static).update(literal(title))
        self.query_one('#question').display=True
        self.query_one('#choice_hint',Static).update(literal(hint or 'Enter continue · Esc cancel'))
        self.query_one('#choice_hint').display=True
        field=self.query_one('#prompt',Input)
        field.password=secret
        field.placeholder='Hidden key · Enter to continue' if secret else '›  Enter a value'
        field.focus()

    def on_option_list_option_selected(self,event):
        if self.answer_callback and not self.text_answer and not self.busy:
            callback=self.answer_callback
            label,value=self.choice_values[event.option_index]
            self.clear_question()
            self.write_note('› '+label)
            callback(value)

    def action_cancel_input(self):
        if self.answer_callback and not self.busy:
            self.clear_question()
            self.write_note('Choice cancelled. No job was submitted by this choice.')
            self.render_context()

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
        if not self.answer_callback:
            self.query_one('#prompt',Input).placeholder='›  Ask about this configuration, or /help' if provider else '›  /convert  /open  /model  /help'

    def on_input_submitted(self,event:Input.Submitted):
        if self.busy:
            return
        text=event.value.strip()
        event.input.value=''
        if self.answer_callback and self.text_answer:
            callback=self.answer_callback
            secret=event.input.password
            self.clear_question()
            if text and not secret:
                self.write_note('› '+text)
            callback(text)
        elif text:
            # Never echo arbitrary free text or credentials into conversation history.
            self.dispatch(text)

    def dispatch(self,text,quiet=False):
        if self.busy or self.answer_callback:
            return
        if text in {'/clear','/home'}:
            if text=='/clear':
                self.query_one(RichLog).clear()
            self.welcome()
            return
        if text=='/help':
            self.query_one(RichLog).write(help_view())
            return
        if text=='/open':
            self.guided.open()
            return
        if text=='/model':
            self.guided.model()
            return
        if text=='/convert':
            self.guided.convert()
            return
        if text=='/analyze' and not self.controller.state.get('selected'):
            self.guided.open('analyze')
            return
        if text in {'/flow','/dependencies'}:
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
        self.render_context()
        self.run_command(text,quiet)

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
        self.query_one(RichLog).write(heading('Model connection',literal(message)))
        self.render_context()
        self.query_one('#prompt',Input).focus()

    def connect_model_inline(self,name,model,key):
        self.busy=True
        self.write_note('Testing a synthetic model tool call…')
        self.test_model(name,model,key)

    @work(thread=True,exclusive=True,group='model')
    def test_model(self,name,model,key):
        from .setup import connect_model,save_model
        provider=None
        try:
            provider=connect_model(name,model,key)
            stored=save_model(self.controller.workspace.root,provider)
        except Exception as exc:
            if provider:
                provider.close()
            message=str(exc) if isinstance(exc,ProviderError) else 'Model setup could not be completed. Check settings and workspace access.'
            self.call_from_thread(self.model_failed,message)
            return
        self.call_from_thread(self.model_connected,provider,stored)

    def model_failed(self,message):
        self.busy=False
        self.show_error(message)
        self.ask_choice('Model connection', [('Retry model setup',True),('Keep current connection / guided commands',False)],
                        lambda retry: self.guided.model() if retry else self.render_context())

    def model_connected(self,provider,stored):
        self.busy=False
        self.model_selected((provider,stored))

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
        self.query_one(RichLog).write(heading('Next step',literal(message,'#eab308')))

    def show_result(self,result,quiet=False):
        log=self.query_one(RichLog)
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
        if not self.answer_callback and len(self.screen_stack)==1 and not self.busy and self.controller.state.get('active_job') and self.last_status not in {'completed','failed','cancelled'}:
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
