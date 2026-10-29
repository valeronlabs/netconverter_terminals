"""Inline keyboard choices. No model controls paths, settings, or credentials.

Every menu is built from the server catalog (``Controller.catalog``): the full
API offers every vendor and path it accepts; a 0.1.x pilot key keeps the
ASA → Palo Alto settings the pilot API requires.
"""
import json
import re
from pathlib import Path

from .catalog import label
from .workspace import WorkspaceError

# Downloaded artifacts are named "<job id>.<file>"; they are outputs, not sources.
_ARTIFACT = re.compile(r'(?:[a-z]{3}_[A-Za-z0-9]{6,}|[0-9a-f]{8}-[0-9a-f-]{27})\.')
_SKIP_SUFFIXES = {'.zip', '.xlsx', '.pdf', '.png', '.jpg', '.jpeg', '.gif', '.docx', '.pptx', '.gz', '.tgz', '.whl'}
# Platforms NetConverter does not convert, checked before any signature so their
# files are never offered as a look-alike (NX-OS read as ArubaOS, SRX as a Junos
# router). (name, code prefix the server would list if it supported it, pattern)
_UNSUPPORTED = [
    ('Cisco NX-OS', 'cisco_nxos', re.compile(
        r'^(?:!Command: show running-config|version \d+\.\d+\(\d+\)|vrf context management|'
        r'feature (?:nxapi|vpc|lacp|interface-vlan|hsrp|scp-server|ospf|bgp)\b)', re.M)),
    ('Juniper SRX', 'juniper_srx', re.compile(
        r'^(?:set security (?:zones|policies|nat) |\s*security-zone \S+ \{)', re.M)),
]
# First match wins; only codes the server offers are ever suggested. A code ending
# in "_" is a family whose switch/router member is chosen from the content.
_SIGNATURES = [
    ('cisco_asa', re.compile(r'^(?:ASA Version|: Saved|access-list \S+ extended|object-group network)', re.M)),
    ('fortinet', re.compile(r'^config (?:firewall|system) ', re.M)),
    ('palo_alto_panorama', re.compile(r'<(?:device-group|panorama)>')),
    ('palo_alto_xml', re.compile(r'<config\b')),
    ('palo_alto_set', re.compile(r'^set (?:deviceconfig|rulebase|address|zone|network|shared) ', re.M)),
    ('juniper_set_', re.compile(r'^set (?:system|interfaces|protocols|security|vlans|routing-options) ', re.M)),
    ('juniper_junos_', re.compile(r'^(?:system|interfaces|protocols|security|vlans) \{', re.M)),
    ('aruba_cx_switch', re.compile(r'^(?:!Version ArubaOS-CX|vsx$|interface 1/1/)', re.M)),
    # ArubaOS-Switch writes quoted VLAN names and tagged/untagged port lists; Cisco's
    # "vlan 10 / name USERS" has neither (valeronlabs#5).
    ('aruba_os_switch', re.compile(
        r'Configuration Editor|^vlan \d+\s*\n\s+name "|^\s+(?:un)?tagged (?:\d|[A-Z]\d|Trk)', re.M)),
    ('cisco_ios_xe_', re.compile(
        r'^(?:Building configuration|version 1[5-7]\.|interface (?:Gigabit|TenGigabit|Fast)Ethernet|ip routing|'
        r'spanning-tree mode |vlan \d+\s*\n name \S|\s+switchport mode )', re.M)),
    ('cisco_fmc', re.compile(r'"(?:accessPolicies|deviceRecords|objects)"\s*:')),
]
# Switching content: access/trunk ports, a VLAN table, spanning tree.
_SWITCHING = re.compile(r'^(?:\s*switchport\b|spanning-tree mode |vlan \d+\s*$|interface Vlan\d|vlans \{|set vlans |'
                        r'\s*family ethernet-switching)', re.M)


def unsupported_vendor(text, candidates=()):
    """The name of a platform NetConverter does not support, when the file is one; else None."""
    for name, prefix, pattern in _UNSUPPORTED:
        if pattern.search(text) and not any(c.startswith(prefix) for c in candidates):
            return name
    return None


def guess_vendor(text, candidates):
    """A suggested source vendor, read locally from the file head; None when unsure."""
    if unsupported_vendor(text, candidates):
        return None
    for code, pattern in _SIGNATURES:
        if pattern.search(text):
            if code.endswith('_'):
                preferred = code + ('switch' if _SWITCHING.search(text) else 'router')
                if preferred in candidates:
                    return preferred
            for candidate in candidates:
                if candidate == code or (code.endswith('_') and candidate.startswith(code)):
                    return candidate
    return None


class Guided:
    def __init__(self, app):
        self.app = app
        self.root = app.controller.workspace.root
        self.options = {}
        self.job_type = None
        self.filename = None
        self.vendor = None
        self.model_name = None
        self.model_id = None

    @property
    def controller(self):
        return self.app.controller

    @property
    def catalog(self):
        return self.app.controller.catalog

    def choose(self, title, choices, callback, highlight=0):
        self.app.ask_choice(title, choices, callback, highlight=highlight)

    def text(self, title, callback, *, secret=False, hint=''):
        self.app.ask_text(title, callback, secret=secret, hint=hint)

    # -- entry points ----------------------------------------------------------

    def start(self, job_type):
        """/convert, /validate, /optimize (job_type) or /open (None)."""
        if not self.catalog.loaded:
            self.app.load_catalog(lambda: self.start(job_type))
            return
        if job_type and not self.catalog.supports(job_type):
            self.app.show_error(f'{label(job_type)} is not available for this credential yet. '
                                f'Available: {", ".join(label(t) for t in self.catalog.job_types)}.')
            return
        self.job_type = job_type
        self.options = {}
        selected = self.selected()
        if job_type and selected and selected.get('vendor') in self.catalog.sources(job_type):
            name = selected.get('display_name') or selected.get('path')
            self.choose(f'{label(job_type)} which configuration?', [
                (f'{name} · {self.catalog.name(selected["vendor"])}', True),
                ('Choose another file', False)],
                lambda keep: self.after_open(job_type) if keep else self.browse())
            return
        if job_type and selected.get('vendor'):
            self.app.write_note(f'{self.catalog.name(selected["vendor"])} is not a {label(job_type).lower()} source '
                                f'on this server; choose the source file.')
        self.browse()

    def convert(self):
        self.start('convert')

    def open(self, following=None, folder=None):
        self.job_type = following if following in {'convert', 'validate', 'optimize'} else None
        self.browse(folder)

    def selected(self):
        state = self.controller.state
        return state.get('configurations', {}).get(state.get('selected'), {})

    # -- file and source vendor ------------------------------------------------

    def browse(self, folder=None):
        folder = Path(folder or self.root)
        limit = self.controller.max_bytes()
        choices = []
        if folder != self.root:
            choices.append(('↰ ..', folder.parent))
        try:
            entries = sorted(folder.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
            for path in entries:
                if path.name.startswith(('.', '~$')) or path.is_symlink() or _ARTIFACT.match(path.name):
                    continue
                if not path.resolve().is_relative_to(self.root):
                    continue
                if path.is_dir():
                    choices.append((path.name + '/', path))
                elif path.suffix.lower() not in _SKIP_SUFFIXES:
                    size = path.stat().st_size
                    if size:
                        over = f'  · over the {_size(limit)} limit' if size > limit else ''
                        choices.append((f'{path.name}  ·  {_size(size)}{over}', path))
        except OSError:
            self.app.show_error('Cannot list this folder. Check its permissions.')
        choices = choices[:200] + [('Type a relative file path', None)]
        title = {'convert': 'Convert which file?', 'validate': 'Validate which file?',
                 'optimize': 'Optimize which file?'}.get(self.job_type, 'Choose a configuration')
        self.choose(title, choices, lambda path: self.file_chosen(path, folder))

    def file_chosen(self, path, folder=None):
        if path is None:
            self.text('Relative configuration path',
                      lambda value: self.file_chosen(self.root / value.strip().strip('"'), folder))
            return
        try:
            path = self.controller.workspace._inside(Path(path))
            if path.is_dir():
                self.browse(path)
                return
            _, content, _ = self.controller.workspace.snapshot(str(path.relative_to(self.root)),
                                                               self.controller.max_bytes())
        except (WorkspaceError, OSError):
            self.app.show_error(f'Choose a UTF-8 text configuration inside this folder, '
                                f'up to {self.controller.max_bytes():,} bytes.')
            self.browse(folder)
            return
        self.filename = str(path.relative_to(self.root))
        sources = self.catalog.sources(self.job_type or 'validate')
        if len(sources) == 1:
            self.vendor_chosen(sources[0])
            return
        choices = self.catalog.grouped(sources)
        head = content[:65536].decode('utf-8', 'replace')
        unsupported = unsupported_vendor(head, [c for _, c in choices])
        if unsupported:
            self.app.write_note(f'{Path(self.filename).name} looks like {unsupported}, which is '
                                'not supported yet. Choose a vendor below only if the file is something else.')
        guess = guess_vendor(head, [c for _, c in choices])
        highlight = 0
        if guess:
            highlight = [c for _, c in choices].index(guess)
            choices[highlight] = (choices[highlight][0] + '  · detected', guess)
        self.choose(f'What does {Path(self.filename).name} contain?', choices, self.vendor_chosen,
                    highlight=highlight)

    def vendor_chosen(self, vendor):
        self.vendor = vendor
        if self.controller.external:
            # Nothing leaves this machine until the review's explicit Submit.
            self.app.open_selected((self.filename, vendor, self.job_type))
            return
        self.choose(f'Upload {self.filename} as {self.catalog.name(vendor)}?', [
            ('Upload this file directly to NetConverter', True), ('Choose another file', False)],
            lambda approved: self.app.open_selected((self.filename, vendor, self.job_type))
            if approved else self.browse())

    def after_open(self, following):
        """Called once the selected configuration is pinned (uploaded for pilot keys)."""
        self.job_type = following
        self.options = {}
        if following == 'convert':
            self.target()
        elif following in {'validate', 'optimize'}:
            self.review()

    # -- conversion settings ---------------------------------------------------

    def target(self):
        source = self.selected().get('vendor')
        targets = self.catalog.targets(source)
        if not targets:
            self.app.show_error(f'{self.catalog.name(source)} has no conversion target on this server. '
                                f'Use /validate to check it instead.')
            return

        def chosen(value):
            self.options['target_vendor'] = value
            if self.catalog.profile == 'quick':
                self.quick_fields([('panos_target_version', 'panos_versions', 'PAN-OS version'),
                                   ('routing_engine', 'routing_engines', 'Routing engine'),
                                   ('pipeline_mode', 'pipeline_modes', 'Conversion mode')])
            else:
                self.full_settings()
        self.choose(f'Convert {self.catalog.name(source)} to', self.catalog.grouped(targets), chosen)

    def full_settings(self):
        """Full API (#19): the same Advanced and Zone screens, sent as a YAML v2 document.

        Every setting is optional here: the defaults choice sends no decisions at all,
        and only settings ``job_options`` maps for this target are asked.
        """
        def answer(customize):
            if not customize:
                self.review()
            elif self.options['target_vendor'] == 'palo_alto_panorama':
                self.optional_text('Panorama device group (Enter for the server default)',
                                   'panorama_device_group',
                                   lambda: self.optional_text('Panorama template (Enter for the server default)',
                                                              'panorama_template', self.cleanup))
            else:
                self.cleanup()
        self.choose('Conversion settings', [('Use NetConverter’s defaults', False),
                                            ('Customize cleanup, App-ID, profiles, logging and zone mapping',
                                             True)], answer)

    def optional_text(self, title, field, following):
        def answer(value):
            if value.strip():
                self.options[field] = value.strip()
            following()
        self.text(title, answer)

    def quick_fields(self, fields):
        """Pilot keys: the pilot API requires these Palo Alto settings explicitly."""
        if not fields:
            self.panorama()
            return
        field, key, title = fields[0]
        values = self.catalog.quick.get(key) or []
        if not values:
            self.app.show_error('Load supported settings with /refresh, then use /convert.')
            return

        def selected(value):
            self.options[field] = value
            self.quick_fields(fields[1:])
        self.choose(title, [(label(v), v) for v in values], selected)

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
            if self.catalog.profile != 'quick':  # full API: already chose to customize
                self.advanced()
                return
            self.choose('Advanced settings', [('Use the selected mode’s server presets', False),
                                              ('Customize App-ID, profiles, logging and mappings', True)],
                        lambda customize: self.advanced() if customize else self.review())
        self.choose('Remove unused objects during validated conversion?',
                    [('Keep existing objects', False), ('Remove verified unused objects', True)], answer)

    def advanced(self, index=0):
        preset = 'Use mode preset' if self.catalog.profile == 'quick' else 'Use the server default'
        choices = [
            ('enable_appid', 'App-ID', [(preset, None), ('Enable', True), ('Disable', False)]),
            ('app_id_implementation', 'App-ID implementation',
             [(preset, None), ('Stack above original', 'dual_stack'), ('Replace original', 'force')]),
            ('add_security_profiles', 'Security profiles', [(preset, None), ('Enable', True), ('Disable', False)]),
            ('log_all_rules', 'Log all rules', [(preset, None), ('Enable', True), ('Disable', False)]),
            ('implicit_deny', 'Explicit deny-all',
             [(preset, None), ('Enable', 'explicit-deny-all'), ('Disable', 'none')])]
        if index == len(choices):
            if str(self.options.get('target_vendor', '')).startswith('palo_alto'):
                self.text('Security profile group (Enter to use preset)', self.profile_group)
            else:  # a profile group is a Palo Alto setting; job_options refuses it elsewhere
                self.profile_group('')
            return
        field, title, options = choices[index]

        def answer(value):
            if value is not None:
                self.options[field] = value
            self.advanced(index + 1)
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
                if not isinstance(mapping, dict) or not all(isinstance(k, str) and isinstance(v, str)
                                                            for k, v in mapping.items()):
                    raise ValueError()
                self.options['zone_mapping'] = mapping
            except ValueError:
                self.app.show_error('Use a JSON object of source and target zone names.')
                self.text('Zone mapping JSON (Enter for no override)', self.zone_mapping)
                return
        self.review()

    # -- review and submit -----------------------------------------------------

    def review(self):
        from .presentation import card, details_view, literal
        selected = self.selected()
        from rich.console import Group
        from .palette import MUTED
        summary = {'job_type': self.job_type, 'file': selected.get('display_name') or selected.get('path'),
                   'source_vendor': self.catalog.name(selected.get('vendor'))}
        for field, value in self.options.items():
            summary[field] = self.catalog.name(value) if field == 'target_vendor' else value
        cost = {'convert': 'one conversion', 'validate': 'one analysis', 'optimize': 'one analysis'}[self.job_type]
        sends = ('Submit sends the file directly to NetConverter over HTTPS'
                 if self.controller.external else 'Submit starts the job on NetConverter')
        self.app.write(card('Review', Group(details_view(summary), literal(''),
                                            literal(f'{sends} and uses {cost}.', MUTED))))
        self.choose('Submit this job?',
                    [('Submit to NetConverter', True), ('Start over', False)],
                    lambda submit: self.app.submit_job(self.job_type, self.options) if submit
                    else self.start(self.job_type))

    # -- model ------------------------------------------------------------------

    def model(self):
        self.choose('Model provider', [('OpenAI', 'openai'), ('Anthropic', 'anthropic'), ('Gemini', 'gemini'),
                                       ('Ollama · local', 'ollama'), ('Guided commands · no model', 'none')],
                    self.provider)

    def provider(self, name):
        self.model_name = name
        if name == 'none':
            self.app.connect_model_inline(name, '', '')
        else:
            self.text('Exact API model ID', self.model_value, hint='Use a model available to your API account.')

    def model_value(self, value):
        if not value.strip():
            self.app.show_error('Enter an explicit model ID.')
            self.provider(self.model_name)
            return
        self.model_id = value.strip()
        if self.model_name == 'ollama':
            self.app.connect_model_inline(self.model_name, self.model_id, '')
        else:
            self.text(f'{self.model_name} API key · hidden',
                      lambda key: self.app.connect_model_inline(self.model_name, self.model_id, key.strip()),
                      secret=True, hint='Paste here; Enter uses a saved key if available. '
                                        'This value is never added to the conversation.')

    # -- AI clients --------------------------------------------------------------

    def connect(self):
        from .connect import CLIENTS, configured_clients, plan
        done = configured_clients(self.root)
        self.choose('Connect which AI assistant to this folder?',
                    [(spec.title + (' · already connected' if spec.title in done else ''), key)
                     for key, spec in CLIENTS.items()],
                    lambda key: self.connect_review(plan(key, self.root)))

    def connect_review(self, change):
        from .presentation import card, literal
        from .palette import MUTED
        from rich.console import Group
        from .connect import CLIENTS
        heading = f'Connect {change.title}' if change.key in CLIENTS else change.title
        self.app.write(card(heading, Group(literal(change.summary), literal(change.preview, MUTED))))
        if not change.can_apply:
            self.app.write_note(change.manual)
            return
        self.choose(f'Apply this change to {change.where}?', [('Apply', True), ('Cancel', False)],
                    lambda ok: self.app.apply_connect(change) if ok else self.app.write_note('Nothing was changed.'))


def _size(value):
    if value >= 1024 * 1024:
        return f'{value / 1024 / 1024:.1f} MB'
    if value >= 1024:
        return f'{value / 1024:.0f} KB'
    return f'{value} B'
