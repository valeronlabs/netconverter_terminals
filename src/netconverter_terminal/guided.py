"""Inline keyboard choices. No model controls paths, settings, or credentials."""
import json
from pathlib import Path
from .workspace import WorkspaceError


class Guided:
    def __init__(self, app):
        self.app = app
        self.root = app.controller.workspace.root
        self.options = {}
        self.model_name = None
        self.model_id = None

    def choose(self, title, choices, callback):
        self.app.ask_choice(title, choices, callback)

    def text(self, title, callback, *, secret=False, hint=''):
        self.app.ask_text(title, callback, secret=secret, hint=hint)

    def open(self, following=None, folder=None):
        folder = Path(folder or self.root)
        choices = []
        if folder != self.root:
            choices.append(('.. /', folder.parent))
        try:
            entries = sorted(folder.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
            for path in entries:
                if path.name.startswith(('.', 'trm_', 'tra_', 'psc_', 'opt_')) or path.is_symlink():
                    continue
                if not path.resolve().is_relative_to(self.root):
                    continue
                if path.is_dir():
                    choices.append((path.name+'/', path))
                elif path.suffix.lower() in {'.asa', '.cfg', '.conf', '.txt', '.set', '.xml'}:
                    choices.append((f'{path.name}  ·  {path.stat().st_size:,} bytes', path))
        except OSError:
            self.app.show_error('Cannot list this folder. Check its permissions.')
        choices = choices[:200] + [('Enter a relative file path', None)]
        self.choose('Choose an ASA source file' if following == 'convert' else 'Choose a configuration', choices,
                    lambda path: self.file_chosen(path, following))

    def file_chosen(self, path, following):
        if path is None:
            self.text('Relative configuration path', lambda value: self.file_chosen(self.root / value.strip().strip('"'), following))
            return
        try:
            path = self.app.controller.workspace._inside(Path(path))
            if path.is_dir():
                self.open(following, path)
                return
            self.app.controller.workspace.snapshot(str(path.relative_to(self.root)))
        except (WorkspaceError, OSError):
            self.app.show_error('Choose a UTF-8 configuration inside this folder, between 1 and 50,000 bytes.')
            self.open(following)
            return
        self.filename = str(path.relative_to(self.root))
        if following == 'convert':
            self.confirm_upload('cisco_asa', following)
        else:
            self.choose('Source format — what this file contains', [
                ('Cisco ASA', 'cisco_asa'), ('Palo Alto SET', 'palo_alto_set'),
                ('Palo Alto XML', 'palo_alto_xml'), ('Panorama', 'palo_alto_panorama')],
                lambda vendor: self.confirm_upload(vendor, following))

    def confirm_upload(self, vendor, following):
        self.choose(f'Upload {self.filename} as {vendor}?', [
            ('Upload this file directly to NetConverter', True), ('Choose another file', False)],
            lambda approved: self.app.open_selected((self.filename, vendor, following)) if approved else self.open(following))

    def convert(self):
        state = self.app.controller.state
        selected = state.get('configurations', {}).get(state.get('selected'), {})
        if selected.get('vendor') != 'cisco_asa':
            if selected:
                self.app.write_note('ASA → Palo Alto migration needs an ASA source. Select the ASA file next; Palo Alto files can be analyzed with /analyze.')
            self.open('convert')
            return
        caps = self.app.controller.allowance
        fields = [('target_vendor', 'targets', 'Palo Alto output'),
                  ('panos_target_version', 'panos_versions', 'PAN-OS version'),
                  ('routing_engine', 'routing_engines', 'Routing engine'),
                  ('pipeline_mode', 'pipeline_modes', 'Conversion mode')]
        if any(not caps.get(key) for _, key, _ in fields):
            self.app.show_error('Load supported settings with /allowance, then use /convert.')
            return
        self.options = {}
        self.conversion_fields(fields)

    def conversion_fields(self, fields):
        if not fields:
            self.panorama()
            return
        field, key, title = fields[0]
        labels = {'palo_alto_set':'SET commands', 'palo_alto_xml':'PAN-OS XML', 'palo_alto_panorama':'Panorama',
                  'vr':'Virtual router (vr)', 'lr':'Logical router (lr)', 'like_for_like':'Like for like', 'ai_recommended':'AI recommended'}
        def selected(value):
            self.options[field] = value
            self.conversion_fields(fields[1:])
        self.choose(title, [(labels.get(v,v),v) for v in self.app.controller.allowance[key]], selected)

    def panorama(self):
        if self.options['target_vendor'] == 'palo_alto_panorama':
            self.required_text('Panorama device group', 'panorama_device_group',
                lambda: self.required_text('Panorama template', 'panorama_template', self.cleanup))
        else:
            self.cleanup()

    def required_text(self, title, field, following):
        def answer(value):
            if not value.strip():
                self.app.show_error('This value is required.')
                self.required_text(title, field, following)
            else:
                self.options[field] = value.strip()
                following()
        self.text(title, answer)

    def cleanup(self):
        def answer(value):
            self.options['remove_unused_objects'] = value
            self.choose('Advanced settings', [('Use the selected mode’s server presets',False), ('Customize App-ID, profiles, logging and mappings',True)],
                        lambda customize: self.advanced() if customize else self.review())
        self.choose('Remove unused objects during validated conversion?', [('Keep existing objects',False), ('Remove verified unused objects',True)], answer)

    def advanced(self, index=0):
        choices = [
            ('enable_appid','App-ID',[('Use mode preset',None),('Enable',True),('Disable',False)]),
            ('app_id_implementation','App-ID implementation',[('Use mode preset',None),('Stack above original','dual_stack'),('Replace original','force')]),
            ('add_security_profiles','Security profiles',[('Use mode preset',None),('Enable',True),('Disable',False)]),
            ('log_all_rules','Log all rules',[('Use mode preset',None),('Enable',True),('Disable',False)]),
            ('implicit_deny','Explicit deny-all',[('Use mode preset',None),('Enable','explicit-deny-all'),('Disable','none')])]
        if index == len(choices):
            self.text('Security profile group (Enter to use preset)', self.profile_group)
            return
        field, title, options = choices[index]
        def answer(value):
            if value is not None:
                self.options[field] = value
            self.advanced(index+1)
        self.choose(title, options, answer)

    def profile_group(self, value):
        if value.strip():
            self.options['default_profile_group'] = value.strip()
        self.text('Zone mapping JSON (Enter for no override)', self.zone_mapping,
                  hint='Example: {"inside":"Trust"}. Values go directly to NetConverter.')

    def zone_mapping(self, value):
        if value.strip():
            try:
                mapping = json.loads(value)
                if not isinstance(mapping,dict) or not all(isinstance(k,str) and isinstance(v,str) for k,v in mapping.items()):
                    raise ValueError()
                self.options['zone_mapping'] = mapping
            except ValueError:
                self.app.show_error('Use a JSON object of source and target zone names.')
                self.text('Zone mapping JSON (Enter for no override)', self.zone_mapping)
                return
        self.review()

    def review(self):
        from .presentation import heading, details_view
        self.app.query_one('#conversation').write(heading('Review conversion settings',details_view(self.options)))
        self.choose('Submit this conversion? One target uses one conversion allowance.',
                    [('Submit to NetConverter',True),('Start choices again',False)],
                    lambda submit: self.app.submit_conversion(self.options) if submit else self.convert())

    def model(self):
        self.choose('Model provider', [('OpenAI','openai'),('Anthropic','anthropic'),('Gemini','gemini'),('Ollama · local','ollama'),('Guided commands · no model','none')], self.provider)

    def provider(self, name):
        self.model_name = name
        if name == 'none':
            self.app.connect_model_inline(name,'','')
        else:
            self.text('Exact API model ID', self.model_value, hint='Use a model available to your API account.')

    def model_value(self, value):
        if not value.strip():
            self.app.show_error('Enter an explicit model ID.')
            self.provider(self.model_name)
            return
        self.model_id = value.strip()
        if self.model_name == 'ollama':
            self.app.connect_model_inline(self.model_name,self.model_id,'')
        else:
            self.text(f'{self.model_name} API key · hidden',
                      lambda key: self.app.connect_model_inline(self.model_name,self.model_id,key.strip()),
                      secret=True,hint='Paste here; Enter uses a saved key if available. This value is never added to the conversation.')
