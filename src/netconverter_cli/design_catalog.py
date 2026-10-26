"""Generated server operation schemas, with no local migration compiler."""
import json
from importlib.resources import files

CATALOG = json.loads(files('netconverter_cli').joinpath('guided_operations.json').read_text())
TYPED_CHANGE_SCHEMA = {'oneOf': [
    {'type': 'object', 'additionalProperties': False, 'required': ['operation', 'parameters'],
     'properties': {'operation': {'const': name}, 'parameters': entry['parameters']}}
    for name, entry in CATALOG['operations'].items() if entry.get('preparation_supported')
]}
