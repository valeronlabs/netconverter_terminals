"""/cd, /ls, /dir and /pwd: the user moves between folders; the model cannot."""
import pytest
from textual.widgets import RichLog

from netconverter_cli.commands import execute
from netconverter_cli.providers import OPERATIONS
from netconverter_cli.tui import Terminal
from netconverter_cli.workspace import WorkspaceError

from tests.test_cli_020 import external, settle


def _tree(root):
    (root / "site-a").mkdir()
    (root / "site-a" / "edge.cfg").write_text("hostname SYNTHETIC-A\n")
    (root / "notes.txt").write_text("x" * 2048)
    (root / ".hidden").write_text("secret")


def test_ls_lists_folders_first_with_sizes_and_hides_dotfiles(tmp_path):
    _tree(tmp_path)
    controller, _ = external(tmp_path)
    listing = execute(controller, "/ls")
    names = [e["name"] for e in listing["entries"]]
    assert names == ["site-a", "notes.txt"]
    assert listing["entries"][0]["folder"] and listing["entries"][1]["bytes"] == 2048
    assert execute(controller, "/dir site-a")["entries"][0]["name"] == "edge.cfg"


def test_cd_switches_the_workspace_and_its_own_job_state(tmp_path):
    _tree(tmp_path)
    controller, _ = external(tmp_path)
    controller.state["jobs"]["tra_000000000001"] = {}
    controller.workspace.store(controller.state)
    result = execute(controller, "/cd site-a")
    assert result["folder"] == str((tmp_path / "site-a").resolve())
    assert controller.workspace.root == (tmp_path / "site-a").resolve()
    assert controller.state["jobs"] == {}  # each folder keeps its own jobs
    assert execute(controller, "/pwd")["folder"] == str(controller.workspace.root)
    back = execute(controller, "/cd ..")
    assert back["jobs_here"] == 1


def test_cd_refuses_missing_and_readonly_folders_without_switching(tmp_path):
    controller, _ = external(tmp_path)
    with pytest.raises(WorkspaceError, match="Not a folder"):
        execute(controller, "/cd nowhere")
    locked = tmp_path / "locked"
    locked.mkdir()
    locked.chmod(0o500)
    try:
        with pytest.raises(WorkspaceError, match="not writable"):
            execute(controller, "/cd locked")
    finally:
        locked.chmod(0o700)
    assert controller.workspace.root == tmp_path.resolve()


def test_folder_commands_are_not_model_operations():
    assert not {"cd", "ls", "dir", "pwd"} & set(OPERATIONS)


@pytest.mark.asyncio
async def test_tui_cd_and_ls_render_and_update_the_folder(tmp_path):
    _tree(tmp_path)
    controller, _ = external(tmp_path)
    app = Terminal(controller)
    async with app.run_test(size=(126, 41)) as pilot:
        await settle(app, pilot)
        app.dispatch("/ls")
        await pilot.pause()
        app.dispatch("/cd site-a")
        await pilot.pause()
        text = "\n".join(line.text for line in app.query_one(RichLog).lines)
        assert "site-a/" in text and "notes.txt" in text and ".hidden" not in text
        assert "Now working in" in text and "edge.cfg" in text
        assert controller.workspace.root.name == "site-a"
