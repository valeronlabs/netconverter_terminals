"""docs/CLI_REFERENCE.md is generated from the argparse definitions and must stay current."""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _generator():
    spec = importlib.util.spec_from_file_location("gen_cli_reference", ROOT / "scripts" / "gen_cli_reference.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_every_command_has_help_and_an_example():
    assert _generator().missing() == []


def test_reference_is_current():
    gen = _generator()
    assert (ROOT / "docs" / "CLI_REFERENCE.md").read_text(encoding="utf-8") == gen.render(), \
        "run: python scripts/gen_cli_reference.py"


def test_guide_anchors_used_by_the_reference_exist():
    guide = (ROOT / "docs" / "GUIDE.md").read_text(encoding="utf-8")
    for heading in ("## Sign-in and credentials", "## Privacy and exposure levels",
                    "## AI assistants and the MCP bridge", "## Guided migration (prescan, decisions, conversion)",
                    "## Confirmations before an upload or a conversion", "## Error codes and what to do"):
        assert heading in guide
