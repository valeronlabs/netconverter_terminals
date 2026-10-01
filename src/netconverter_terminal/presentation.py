"""Human-readable local results; all server strings are literal, never markup."""
import re
from rich.console import Group
from rich.table import Table
from rich.text import Text
from rich.padding import Padding

BLUE = '#3b82f6'
MUTED = '#8b8b8d'


def literal(value, style=''):
    value = str(value)
    value = re.sub(r'[\x00-\x08\x0b-\x1f\x7f]', '', value)
    return Text(value, style=style)


def heading(title, body):
    return Padding(Group(literal(title, 'bold '+BLUE), body), (0, 0, 1, 0))


def help_view():
    table = Table.grid(padding=(0, 3))
    table.add_column(style=BLUE, no_wrap=True)
    table.add_column()
    for command, description in [
        ('/open', 'Choose a file and confirm its source format/upload'),
        ('/convert', 'ASA file → Palo Alto output → review → submit'),
        ('/analyze', 'Analyze the selected configuration'),
        ('/unused_objects', 'Explain unused objects after analysis'),
        ('/routes  /policy  /nat', 'Inspect supported findings'),
        ('/optimize', 'Get optimization recommendations'),
        ('/jobs  /resume JOB_ID', 'Find or resume a server job'),
        ('/target', 'Select a generated target, then /analyze it'),
        ('/download', 'Save verified artifacts beside the source'),
        ('/model', 'Connect or change your model; keys are hidden'),
        ('/allowance', 'Refresh your remaining allowance'),
        ('/flow  /dependencies', 'Show structured parameter examples'),
        ('/clear', 'Clear the visible conversation'),
    ]:
        table.add_row(command, description)
    return heading('Commands', table)


def details_view(value, depth=0):
    if depth >= 4:
        return literal('Further detail is available in the saved report.', MUTED)
    if isinstance(value, dict):
        table = Table.grid(padding=(0,2), expand=True)
        table.add_column(ratio=1, style=MUTED)
        table.add_column(ratio=3)
        for key, child in list(value.items())[:40]:
            table.add_row(literal(str(key).replace('_',' ')), details_view(child, depth+1))
        if len(value)>40:
            table.add_row('', literal('More fields in the saved report.', MUTED))
        return table
    if isinstance(value, list):
        if not value:
            return literal('None')
        rows=[]
        for item in value[:12]:
            rows.append(details_view(item,depth+1))
            if isinstance(item,dict):
                rows.append(Text(''))
        if len(value)>12:
            rows.append(literal(f'{len(value)-12} more items in the saved report.',MUTED))
        return Group(*rows)
    return literal('Yes' if value is True else 'No' if value is False else '—' if value is None else value)


def jobs_view(jobs, state=None, compact=False):
    state=state or {}
    table=Table(box=None, padding=(0,1), expand=True)
    columns=('Job','Type','Status') if compact else ('Job','Type','Source','Target','Status','Submitted')
    for column in columns:
        table.add_column(column, style=BLUE if column=='Job' else '', overflow='fold')
    for job in jobs:
        if not isinstance(job,dict):
            continue
        identity=job.get('job_id') or job.get('id') or '—'
        local=state.get('jobs',{}).get(identity,{})
        source=state.get('configurations',{}).get(job.get('configuration_id') or local.get('configuration_id'),{})
        options=local.get('options',{})
        verdict=job.get('translation_status') or job.get('status','—')
        values=[identity,job.get('operation') or local.get('operation','—')]
        if not compact:
            values.extend([source.get('display_name') or source.get('path','—'),job.get('target_vendor') or options.get('target_vendor','—')])
        values.append(verdict)
        if not compact:
            from datetime import datetime
            timestamp=local.get('submitted_at')
            values.append(job.get('created_at') or (datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M') if isinstance(timestamp,(int,float)) else '—'))
        table.add_row(*(literal(v) for v in values))
    if not jobs:
        return literal('No jobs yet. Use /open to select a configuration.',MUTED)
    return Group(table,Text(''),literal('Use /resume JOB_ID to follow a job and retrieve its files.',MUTED))


def artifacts_view(paths):
    from pathlib import Path
    table=Table(box=None,padding=(0,2),expand=True)
    table.add_column('Local file',style=BLUE,ratio=4)
    table.add_column('Bytes',justify='right')
    table.add_column('Type')
    kinds={'.xlsx':'Evidence workbook','.yaml':'YAML','.yml':'YAML','.txt':'Text report','.json':'JSON','.xml':'XML','.set':'SET configuration'}
    parents=[]
    for value in paths:
        path=Path(value)
        try:
            size=str(path.stat().st_size)
        except OSError:
            size='unavailable'
        table.add_row(literal(path.name),literal(size),literal(kinds.get(path.suffix,'Artifact')))
        if str(path.parent) not in parents:
            parents.append(str(path.parent))
    return Group(table,Text(''),*(literal('Location: '+p,MUTED) for p in parents))
