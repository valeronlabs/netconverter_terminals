"""NetConverter CLI identity: the setup banner and the app's one-row header."""
from pathlib import Path

from rich.table import Table
from rich.text import Text

from . import __version__
from .palette import ACCENT, DIM, ERROR, FG, MUTED, SUCCESS, WARNING

PRODUCT = 'NetConverter CLI'
TAGLINE = 'Any-vendor migrations · your AI over MCP · configs never reach the model'


def wordmark(version=True):
    text = Text('◆ ', style=f'bold {ACCENT}')
    text.append('Net', style=f'bold {FG}')
    text.append('Converter', style=f'bold {ACCENT}')
    if version:
        text.append(f'  v{__version__}', style=MUTED)
    return text


def folder_label(folder):
    label = str(folder)
    home = str(Path.home())
    return '~' + label[len(home):] if label.startswith(home + '/') else label


def banner(folder, compact=False, width=120):
    """Multi-line identity block for `netconverter setup` and plain output."""
    from .presentation import literal
    text = wordmark()
    text.append('  CLI\n', style=f'bold {FG}')
    text.append(TAGLINE + '\n', style=MUTED)
    folder_text = literal('Folder  ' + folder_label(folder), DIM)
    folder_text.truncate(max(16, width - 4), overflow='ellipsis')
    text.append(folder_text)
    return text


def _pill(dot, label, color, value=None):
    text = Text(dot + ' ', style=color)
    text.append(label, style=FG if color != DIM else MUTED)
    if value:
        text.append(' ' + value, style=MUTED)
    return text


def header(width, *, server='checking', profile='', bridge=None, model=None, allowance=''):
    """One row: wordmark left, status pills right; lower-priority pills drop as width shrinks.

    server: connected | checking | offline. bridge: (client, ago) or None.
    """
    server_pill = {
        'connected': _pill('●', 'Server', SUCCESS, profile or None),
        'offline': _pill('●', 'Server', ERROR, 'offline · /allowance'),
    }.get(server, _pill('●', 'Server', WARNING, 'checking'))
    # (priority, pill) in display order; lower priority numbers survive a narrow terminal.
    pills = [(0, server_pill)]
    if bridge:
        pills.append((2, _pill('◆', 'Bridge', ACCENT, f'{bridge[0]} · {bridge[1]}')))
    else:
        pills.append((4, _pill('◇', 'Bridge', DIM, 'idle')))
    pills.append((3, _pill('●', 'Model', SUCCESS, model)) if model else (5, _pill('○', 'Model', DIM, 'none')))
    if allowance:
        pills.append((1, Text(allowance, style=MUTED)))
    left = wordmark()
    budget = max(0, width - left.cell_len - 4)
    kept, used = set(), 0
    for index, (_, pill) in sorted(enumerate(pills), key=lambda item: item[1][0]):
        if used + pill.cell_len + (3 if kept else 0) <= budget:
            kept.add(index)
            used += pill.cell_len + (3 if len(kept) > 1 else 0)
    right = Text('   ').join(pill for index, (_, pill) in enumerate(pills) if index in kept)
    grid = Table.grid(expand=True)
    grid.add_column(no_wrap=True)
    grid.add_column(justify='right', no_wrap=True)
    grid.add_row(left, right)
    return grid
