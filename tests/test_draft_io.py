import os
from pathlib import Path

import pytest

from netconverter_cli.draft_io import secure_snapshot
from netconverter_cli.workspace import Workspace, WorkspaceError


@pytest.fixture
def workspace(tmp_path):
    return Workspace(tmp_path)


def test_snapshot_absolute_and_relative_are_identical(workspace):
    path = workspace.root / "source.cfg"
    path.write_text("hostname synthetic\n")
    assert secure_snapshot(workspace, "source.cfg") == secure_snapshot(workspace, str(path))


@pytest.mark.parametrize("name", ["../outside.cfg", "/etc/passwd", ".netconverter/session.json", "missing", ""])
def test_workspace_confinement(workspace, name):
    with pytest.raises(WorkspaceError):
        secure_snapshot(workspace, name)


def test_symlink_file_or_ancestor_refused(workspace, tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    (real / "source.cfg").write_text("source")
    (tmp_path / "source.cfg").symlink_to(real / "source.cfg")
    (tmp_path / "linked").symlink_to(real, target_is_directory=True)
    for name in ["source.cfg", "linked/source.cfg"]:
        with pytest.raises(WorkspaceError):
            secure_snapshot(workspace, name)


@pytest.mark.parametrize("content", [b"", b"too large", b"a\x00b", b"\xff"])
def test_invalid_content(workspace, content):
    (workspace.root / "source.cfg").write_bytes(content)
    with pytest.raises(WorkspaceError):
        secure_snapshot(workspace, "source.cfg", max_bytes=8)


def test_changed_during_read_refused(workspace, monkeypatch):
    path = workspace.root / "source.cfg"
    path.write_bytes(b"original")
    original = os.read
    def racing_read(fd, count):
        content = original(fd, count)
        path.write_bytes(b"changed-and-longer")
        return content
    monkeypatch.setattr(os, "read", racing_read)
    with pytest.raises(WorkspaceError):
        secure_snapshot(workspace, "source.cfg")


def test_replaced_with_symlink_during_read_refused(workspace, monkeypatch):
    path = workspace.root / "source.cfg"
    path.write_bytes(b"original")
    outside = workspace.root.parent / "outside-synthetic.cfg"
    outside.write_bytes(b"private")
    original = os.read
    replaced = False
    def racing_read(fd, count):
        nonlocal replaced
        content = original(fd, count)
        if not replaced:
            path.unlink()
            path.symlink_to(outside)
            replaced = True
        return content
    monkeypatch.setattr(os, "read", racing_read)
    with pytest.raises(WorkspaceError):
        secure_snapshot(workspace, "source.cfg")


def test_fifo_refused_without_blocking(workspace):
    path = workspace.root / "pipe"
    os.mkfifo(path)
    with pytest.raises(WorkspaceError):
        secure_snapshot(workspace, "pipe")


def test_missing_secure_primitive_fails_closed(workspace, monkeypatch):
    monkeypatch.delattr(os, "O_NOFOLLOW")
    with pytest.raises(WorkspaceError, match="unavailable"):
        secure_snapshot(workspace, "source.cfg")


def publish(workspace, content=b"synthetic: true\n"):
    import hashlib
    from netconverter_cli.draft_io import secure_publish
    return secure_publish(workspace, "draft_1", 1, content, hashlib.sha256(content).hexdigest())


def test_secure_publish_no_clobber_and_equal_retry(workspace):
    path = publish(workspace)
    assert path.name == "draft_1.revision-1.yaml"
    assert publish(workspace) == path
    path.write_text("engineer edits")
    with pytest.raises(WorkspaceError):
        publish(workspace)
    assert path.read_text() == "engineer edits"
    assert not list(workspace.root.glob(".nc-draft-*"))


def test_secure_publish_fifo_or_symlink_never_read(workspace):
    destination = workspace.root / "draft_1.revision-1.yaml"
    os.mkfifo(destination)
    with pytest.raises(WorkspaceError):
        publish(workspace)
    destination.unlink()
    outside = workspace.root.parent / "outside-output.yaml"
    outside.write_text("private")
    destination.symlink_to(outside)
    with pytest.raises(WorkspaceError):
        publish(workspace)
    assert outside.read_text() == "private"


def test_root_swapped_to_symlink_at_publication_cannot_redirect_output(tmp_path, monkeypatch):
    root, moved, outside = tmp_path / "workspace", tmp_path / "moved", tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    workspace = Workspace(root)
    original = os.link
    def racing_link(*args, **kwargs):
        root.rename(moved)
        root.symlink_to(outside, target_is_directory=True)
        return original(*args, **kwargs)
    monkeypatch.setattr(os, "link", racing_link)
    monkeypatch.setattr(os, "supports_dir_fd", os.supports_dir_fd | {racing_link})
    with pytest.raises(WorkspaceError):
        publish(workspace)
    assert not list(outside.iterdir())
    assert not list(moved.iterdir())


def test_destination_swapped_to_fifo_during_open_is_bounded(workspace, monkeypatch):
    destination = workspace.root / "draft_1.revision-1.yaml"
    destination.write_text("synthetic: true\n")
    original = os.open
    def racing_open(path, flags, *args, **kwargs):
        if path == destination.name:
            destination.unlink()
            os.mkfifo(destination)
        return original(path, flags, *args, **kwargs)
    monkeypatch.setattr(os, "open", racing_open)
    monkeypatch.setattr(os, "supports_dir_fd", os.supports_dir_fd | {racing_open})
    with pytest.raises(WorkspaceError):
        publish(workspace)


def test_root_replaced_after_open_before_temp_write_fails_closed(tmp_path, monkeypatch):
    root, moved, outside = tmp_path / "workspace", tmp_path / "moved", tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    workspace = Workspace(root)
    original = os.open
    def racing_open(path, flags, *args, **kwargs):
        fd = original(path, flags, *args, **kwargs)
        if isinstance(path, str) and path.startswith(".nc-draft-"):
            root.rename(moved)
            root.symlink_to(outside, target_is_directory=True)
        return fd
    monkeypatch.setattr(os, "open", racing_open)
    monkeypatch.setattr(os, "supports_dir_fd", os.supports_dir_fd | {racing_open})
    with pytest.raises(WorkspaceError):
        publish(workspace)
    assert not list(outside.iterdir())
    assert not list(moved.iterdir())


@pytest.mark.parametrize("replacement", ["regular", "symlink"])
def test_replaced_temporary_link_source_never_claims_verified_success(workspace, monkeypatch, replacement):
    original = os.link
    outside = workspace.root.parent / "foreign-artifact.yaml"
    outside.write_bytes(b"foreign contents")
    def racing_link(source, destination, *args, **kwargs):
        source_fd = kwargs["src_dir_fd"]
        os.unlink(source, dir_fd=source_fd)
        if replacement == "regular":
            fd = os.open(source, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode=0o600, dir_fd=source_fd)
            try:
                os.write(fd, b"foreign contents")
            finally:
                os.close(fd)
        else:
            os.symlink(outside, source, dir_fd=source_fd)
        return original(source, destination, *args, **kwargs)
    monkeypatch.setattr(os, "link", racing_link)
    monkeypatch.setattr(os, "supports_dir_fd", os.supports_dir_fd | {racing_link})
    with pytest.raises(WorkspaceError):
        publish(workspace)
    destination = workspace.root / "draft_1.revision-1.yaml"
    assert destination.is_symlink() if replacement == "symlink" else destination.read_bytes() == b"foreign contents"
    assert outside.read_bytes() == b"foreign contents"
