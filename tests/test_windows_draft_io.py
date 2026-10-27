"""Windows-native guided transfer acceptance; executed on windows-latest."""
import hashlib
import os
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(sys.platform != 'win32', reason='Windows-native handles required')

from netconverter_cli.draft_io import secure_publish, secure_snapshot
from netconverter_cli.workspace import Workspace, WorkspaceError


def publish(workspace, data=b'synthetic: true\n'):
    return secure_publish(workspace, 'draft_1', 1, data, hashlib.sha256(data).hexdigest())


def test_snapshot_nested_and_absolute_and_publish_retry(tmp_path):
    workspace = Workspace(tmp_path)
    folder = tmp_path / 'nested'
    folder.mkdir()
    source = folder / 'source.cfg'
    source.write_bytes(b'hostname synthetic\n')
    path, data, digest = secure_snapshot(workspace, 'nested/source.cfg')
    assert path == source and digest == hashlib.sha256(data).hexdigest()
    assert secure_snapshot(workspace, str(source))[1:] == (data, digest)
    target = publish(workspace)
    assert target.read_bytes() == b'synthetic: true\n'
    assert publish(workspace) == target
    assert not list(tmp_path.glob('.nc-draft-*'))


def test_never_overwrites_and_refuses_bad_checksum(tmp_path):
    workspace = Workspace(tmp_path)
    target = tmp_path / 'draft_1.revision-1.yaml'
    target.write_bytes(b'engineer edit')
    with pytest.raises(WorkspaceError):
        publish(workspace)
    assert target.read_bytes() == b'engineer edit'
    with pytest.raises(WorkspaceError):
        secure_publish(workspace, 'draft_2', 1, b'payload', '0' * 64)
    assert not (tmp_path / 'draft_2.revision-1.yaml').exists()


@pytest.mark.parametrize('name', ['../secret', '.netconverter/session.json', 'file:stream', ''])
def test_path_escape_and_streams_refused(tmp_path, name):
    with pytest.raises(WorkspaceError):
        secure_snapshot(Workspace(tmp_path), name)


def test_reparse_point_refused(tmp_path):
    outside = tmp_path.parent / ('outside-' + tmp_path.name)
    outside.mkdir()
    (outside / 'secret.cfg').write_text('synthetic')
    link = tmp_path / 'linked'
    try:
        os.symlink(outside, link, target_is_directory=True)
    except OSError:
        pytest.skip('Windows runner does not permit symlink creation')
    with pytest.raises(WorkspaceError):
        secure_snapshot(Workspace(tmp_path), 'linked/secret.cfg')


def test_no_replace_when_destination_appears(tmp_path, monkeypatch):
    from netconverter_cli import windows_draft_io as windows
    workspace = Workspace(tmp_path)
    original = windows._rename
    target = tmp_path / 'draft_1.revision-1.yaml'
    def racing_rename(handle, directory, filename):
        target.write_bytes(b'concurrent')
        return original(handle, directory, filename)
    monkeypatch.setattr(windows, '_rename', racing_rename)
    with pytest.raises(WorkspaceError):
        publish(workspace)
    assert target.read_bytes() == b'concurrent'
    assert not list(tmp_path.glob('.nc-draft-*'))
