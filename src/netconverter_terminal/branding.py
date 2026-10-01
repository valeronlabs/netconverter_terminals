"""Terminal presentation using NetConverter's shared design-system palette."""
from importlib.metadata import version
from pathlib import Path
from rich.text import Text
from rich.table import Table

BLUE = '#3b82f6'
MUTED = '#8b8b8d'


def banner(folder, compact=False, width=120):
    grid = Table.grid(padding=(0, 2))
    grid.add_column(width=19, no_wrap=True)
    grid.add_column(ratio=1)
    mark = Text('┌─────────────────┐\n│ NET', style='bold ' + BLUE)
    mark.append('CONVERTER', style='bold #0a0a0b on '+BLUE)
    mark.append('.ai │\n└─────────────────┘', style='bold '+BLUE)
    title = Text('NET', style='bold #ececec')
    title.append('CONVERTER', style='bold '+BLUE)
    title.append('.ai', style='bold #ececec')
    title.append('  v' + version('netconverter-terminal') + '  ·  PILOT\n', style=MUTED)
    title.append('ASA → Palo Alto only', style='bold ' + BLUE)
    title.append('  ·  SET / XML / Panorama\n', style='#ececec')
    folder_label = str(folder)
    home = str(Path.home())
    if folder_label.startswith(home + '/'):
        folder_label = '~' + folder_label[len(home):]
    from .presentation import literal
    folder_text=literal(folder_label, MUTED)
    folder_text.truncate(max(16,width-(4 if compact else 25)),overflow="ellipsis")
    title.append(folder_text)
    if compact:
        return title
    grid.add_row(mark, title)
    return grid
