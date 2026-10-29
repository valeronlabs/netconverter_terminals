"""Human-readable local results; all server strings are literal, never markup."""
import re
import time
from pathlib import Path

from rich import box
from rich.console import Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .catalog import FIELD_LABELS, label
from .palette import ACCENT, BG, DIM, ERROR, FG, MUTED, SUCCESS, WARNING

BLUE = ACCENT  # 0.1.x name, still imported by callers

# A card is a left accent bar; the bottom edge is blank, so cards space themselves.
_BAR = box.Box("▍   \n▍   \n▍   \n▍   \n▍   \n▍   \n▍   \n    \n")
_KINDS = {
    "info": (ACCENT, ""),
    "success": (SUCCESS, "✓ "),
    "warning": (WARNING, "! "),
    "error": (ERROR, "✕ "),
    "muted": (DIM, ""),
}


def literal(value, style=''):
    value = str(value)
    value = re.sub(r'[\x00-\x08\x0b-\x1f\x7f]', '', value)
    return Text(value, style=style)


def card(title, body, kind='info'):
    color, glyph = _KINDS.get(kind, _KINDS['info'])
    heading_text = literal(glyph + str(title), f'bold {color if kind != "info" else FG}')
    return Panel(body, box=_BAR, title=heading_text, title_align='left', border_style=color,
                 padding=(0, 1), expand=True)


def heading(title, body):
    return card(title, body)


def verdict_style(verdict):
    value = str(verdict or '').lower()
    if value in {'passed', 'completed'}:
        return SUCCESS
    if value in {'failed', 'blocked', 'cancelled'}:
        return ERROR
    if value in {'passed_with_warnings', 'needs_review'}:
        return WARNING
    return MUTED


def badge(verdict):
    value = str(verdict or 'unknown').replace('_', ' ').upper()
    color = verdict_style(verdict)
    if color == MUTED:
        return literal(value.lower(), MUTED)
    # A styled span, not a base style, so table padding does not stretch the pill.
    return Text.assemble((f' {value} ', f'bold {BG} on {color}'))


def commands_table(rows):
    table = Table.grid(padding=(0, 2))
    table.add_column(style=ACCENT, no_wrap=True, min_width=12)
    table.add_column(style=FG)
    for command, description in rows:
        table.add_row(command, description)
    return table


HELP_SECTIONS = [
    ('Work', [
        ('/convert', 'Migrate a configuration to another vendor'),
        ('/validate', 'Check a configuration: readiness, findings, parse gaps'),
        ('/optimize', 'Cleanup and optimization findings'),
        ('/open', 'Choose a configuration without submitting'),
    ]),
    ('Files', [
        ('/ls  /dir [FOLDER]', 'List files and folders (names and sizes only)'),
        ('/cd FOLDER', 'Work in another folder (~, .., absolute or relative)'),
        ('/pwd', 'Show the current folder'),
    ]),
    ('Results', [
        ('/jobs', 'Your server jobs'),
        ('/resume JOB_ID', 'Follow a job and fetch its files'),
        ('/status  /download', 'Refresh the active job · save its files'),
        ('/target', 'Select the generated configuration, then /validate it'),
    ]),
    ('Questions', [
        ('/nat  /policy  /routes', 'Summaries from the active job'),
        ('/interfaces  /unused_objects', 'More summaries'),
        ('/flow  /dependencies', 'Structured traffic and object questions'),
    ]),
    ('Your AI', [
        ('/activity', 'What your AI assistant did through the bridge'),
        ('/connect', 'Wire Claude Code or Desktop, Cursor, VS Code or Codex here'),
        ('/model', 'Connect a model for plain-language questions here'),
    ]),
    ('Session', [
        ('/walkthrough [STEP]', 'A short tour: jobs, privacy, AI integrations'),
        ('/refresh', 'Reconnect and reload server capabilities and limits'),
        ('/clear  /home', 'Clear the conversation · show the start card'),
    ]),
]


def _size(n):
    for unit in ('B', 'KB', 'MB', 'GB'):
        if n < 1024 or unit == 'GB':
            return f'{n:.0f} {unit}' if unit == 'B' else f'{n:.1f} {unit}'
        n /= 1024


def folder_view(listing):
    """/ls: folders first, then files with sizes. Names only, never contents."""
    table = Table.grid(padding=(0, 2))
    table.add_column(style=FG)
    table.add_column(style=MUTED, justify='right')
    for entry in listing['entries']:
        if entry['folder']:
            table.add_row(literal(entry['name'] + '/', ACCENT), '')
        else:
            table.add_row(literal(entry['name']), _size(entry['bytes'] or 0))
    rows = [table] if listing['entries'] else [literal('Empty folder.', MUTED)]
    if listing['total'] > len(listing['entries']):
        rows.append(literal(f"Showing {len(listing['entries'])} of {listing['total']}.", MUTED))
    hint = '/cd NAME to work there · /open "file" VENDOR to choose a configuration'
    if not listing['inside_workspace']:
        hint = 'Outside the current folder · /cd there before opening files'
    rows += [Text(''), literal(hint, MUTED)]
    return card(_home(listing['folder']), Group(*rows))  # the "Saved in" form (#28)


def walkthrough_view(index):
    """One step of the guided tour as a card; commands in the accent color."""
    from .walkthrough import STEPS

    title, lines = STEPS[index]
    body = []
    for line in lines:
        if line.startswith('$ '):
            body.append(literal('  ' + line[2:], ACCENT))
        elif line.startswith('/'):
            body.append(literal('  ' + line, ACCENT))
        else:
            body.append(literal(line, FG))
    footer = (f'/walkthrough {index + 2} for the next step' if index + 1 < len(STEPS)
              else 'That is the tour. /help lists every command.')
    body += [Text(''), literal(footer, MUTED)]
    return card(f'Walkthrough {index + 1}/{len(STEPS)} · {title}', Group(*body))


def help_view():
    table = Table.grid(padding=(0, 2))
    table.add_column(style=ACCENT, no_wrap=True)
    table.add_column(style=FG)
    for index, (section, rows) in enumerate(HELP_SECTIONS):
        if index:
            table.add_row('', '')
        table.add_row(literal(section.upper(), f'bold {MUTED}'), '')
        for command, description in rows:
            table.add_row(command, description)
    hint = literal('Type a command · Esc close · Ctrl+Q quit', MUTED)  # a static card, not a picker (#28)
    return card('Commands', Group(table, Text(''), hint))


def _value(value):
    return literal(label(value))


def details_view(value, depth=0):
    if depth >= 4:
        return literal('Further detail is available in the saved report.', MUTED)
    if isinstance(value, dict):
        table = Table.grid(padding=(0, 2), expand=True)
        table.add_column(style=MUTED, no_wrap=True, min_width=10, max_width=26)
        table.add_column(ratio=1)
        for key, child in list(value.items())[:40]:
            name = FIELD_LABELS.get(key) or str(key).replace('_', ' ').capitalize()
            table.add_row(literal(name), details_view(child, depth + 1))
        if len(value) > 40:
            table.add_row('', literal('More fields in the saved report.', MUTED))
        return table
    if isinstance(value, list):
        if not value:
            return literal('None', MUTED)
        rows = []
        for item in value[:12]:
            rows.append(details_view(item, depth + 1))
        if len(value) > 12:
            rows.append(literal(f'{len(value)-12} more items in the saved report.', MUTED))
        return Group(*rows)
    if value is None:
        return literal('—', MUTED)
    return _value(value)


def ago(timestamp):
    if not isinstance(timestamp, (int, float)):
        return '—'
    seconds = max(0, time.time() - timestamp)
    for unit, size in (('d', 86400), ('h', 3600), ('m', 60)):
        if seconds >= size:
            return f'{int(seconds // size)}{unit} ago'
    return 'just now'


def _when(job, local):
    created = job.get('created_at')
    if isinstance(created, str) and created:
        from datetime import datetime
        try:
            return ago(datetime.fromisoformat(created.replace('Z', '+00:00')).timestamp())
        except ValueError:
            return created[:16]
    return ago(local.get('submitted_at'))


def jobs_view(jobs, state=None, compact=False, catalog=None):
    state = state or {}
    name = catalog.name if catalog else (lambda code: code or '—')
    if not jobs:
        return literal('No jobs yet. Start with /convert or /validate.', MUTED)
    table = Table(box=None, padding=(0, 2), expand=True, header_style=f'bold {MUTED}')
    table.add_column('Job', style=ACCENT, no_wrap=True)
    table.add_column('Type', no_wrap=True)
    if not compact:
        table.add_column('Source → target', ratio=1, overflow='ellipsis', no_wrap=True)
    table.add_column('Verdict', no_wrap=True)
    if not compact:
        table.add_column('When', style=MUTED, no_wrap=True, justify='right')
    for job in jobs:
        if not isinstance(job, dict):
            continue
        identity = job.get('job_id') or job.get('id') or '—'
        local = state.get('jobs', {}).get(identity, {})
        kind = job.get('job_type') or job.get('operation') or local.get('operation') or '—'
        row = [literal(identity), literal(label(kind))]
        if not compact:
            options = local.get('options', {})
            source = job.get('source_vendor') or state.get('configurations', {}).get(
                job.get('configuration_id') or local.get('configuration_id'), {}).get('vendor')
            target = job.get('target_vendor') or options.get('target_vendor')
            route = name(source) + (f' → {name(target)}' if target and target != 'n/a' else '')
            row.append(literal(route))
        verdict = job.get('translation_status') or job.get('status', '—')
        row.append(badge(verdict))
        if not compact:
            row.append(literal(_when(job, local)))
        table.add_row(*row)
    return Group(table, Text(''), literal('/resume JOB_ID follows a job and fetches its files.', MUTED))


def artifacts_view(paths):
    table = Table(box=None, padding=(0, 2), expand=True, header_style=f'bold {MUTED}')
    table.add_column('File', style=ACCENT, ratio=4, overflow='fold')
    table.add_column('Size', justify='right', no_wrap=True)
    table.add_column('Type', no_wrap=True)
    kinds = {'.xlsx': 'Evidence workbook', '.yaml': 'YAML', '.yml': 'YAML', '.txt': 'Text',
             '.json': 'JSON', '.xml': 'XML', '.set': 'SET configuration'}
    parents = []
    for value in paths:
        path = Path(value)
        try:
            size = f'{path.stat().st_size:,} B'
        except OSError:
            size = 'unavailable'
        table.add_row(literal(path.name), literal(size), literal(kinds.get(path.suffix, 'Artifact')))
        if str(path.parent) not in parents:
            parents.append(str(path.parent))
    return Group(table, Text(''), *(literal('Saved in ' + _home(p), MUTED) for p in parents))


def _home(path):
    home = str(Path.home())
    return '~' + path[len(home):] if path.startswith(home + '/') else path


def activity_line(entry):
    """One bridge call as a single line: time · client · tool · what."""
    when = time.strftime('%H:%M', time.localtime(entry.get('ts', 0)))
    text = literal(when + '  ', MUTED)
    text.append(literal((entry.get('client') or 'AI') + '  ', ACCENT))
    tool = entry.get('tool', '?')
    text.append(literal(tool.replace('_', ' ') + '  ', FG))
    if tool == 'submit_file':
        detail = f"{entry.get('path', '?')} · {entry.get('bytes', 0):,} B · sha {str(entry.get('sha256', ''))[:8]}…"
        if entry.get('job_id'):
            detail += f" → {entry['job_id']}"
    elif tool == 'download':
        detail = f"{entry.get('files', 0)} file(s) → {entry.get('path', '.')}"
    else:
        detail = f"{entry.get('job_id', '')} {str(entry.get('status', '')).replace('_', ' ')}".strip()
    text.append(literal(detail, MUTED))
    return text


def activity_view(entries):
    if not entries:
        return literal('No bridge activity in this folder yet. Connect your AI with /connect, '
                       'then ask it to validate a file here.', MUTED)
    return Group(*(activity_line(e) for e in entries),
                 Text(''), literal('Only paths, hashes, sizes and job IDs are recorded — never configuration text.', MUTED))
