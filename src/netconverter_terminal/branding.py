"""Terminal presentation using NetConverter's shared design-system palette."""
from importlib.metadata import version
from pathlib import Path
from rich.text import Text
from rich.table import Table

BLUE = '#3b82f6'
MUTED = '#8b8b8d'


def banner(folder):
    grid = Table.grid(padding=(0, 2))
    grid.add_column(width=9, no_wrap=True)
    grid.add_column(ratio=1)
    mark = Text('┌───────┐\n│ N › C │\n└───────┘', style='bold ' + BLUE)
    title = Text('NetConverter', style='bold #ececec')
    title.append('  v' + version('netconverter-terminal') + '  ·  PILOT\n', style=MUTED)
    title.append('ASA → Palo Alto only', style='bold ' + BLUE)
    title.append('  ·  SET / XML / Panorama\n', style='#ececec')
    folder_label = str(folder)
    home = str(Path.home())
    if folder_label.startswith(home + '/'):
        folder_label = '~' + folder_label[len(home):]
    title.append(folder_label, style=MUTED)
    grid.add_row(mark, title)
    return grid
