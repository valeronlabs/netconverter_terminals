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


def test_snapshot_nested_and_absolute_and_publish_retry(tmp_path, monkeypatch):
    from netconverter_cli import windows_draft_io as windows
    original_rename = windows._rename
    def diagnostic_rename(*args):
        try:
            return original_rename(*args)
        except OSError as exc:
            pytest.fail(f'Native rename failed with Windows error {exc.errno}')
    monkeypatch.setattr(windows, '_rename', diagnostic_rename)
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


def test_matching_existing_file_with_inherited_acl_is_not_reused(tmp_path):
    workspace = Workspace(tmp_path)
    target = tmp_path / 'draft_1.revision-1.yaml'
    target.write_bytes(b'synthetic: true\n')
    with pytest.raises(WorkspaceError):
        publish(workspace)
    assert target.read_bytes() == b'synthetic: true\n'


def test_artifact_dacl_does_not_inherit_workspace_permissions(tmp_path):
    import ctypes
    from ctypes import wintypes
    target = publish(Workspace(tmp_path))
    adv = ctypes.WinDLL('advapi32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    adv.GetNamedSecurityInfoW.argtypes = [wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD,
        wintypes.LPVOID, wintypes.LPVOID, wintypes.LPVOID, wintypes.LPVOID,
        ctypes.POINTER(wintypes.LPVOID)]
    adv.GetNamedSecurityInfoW.restype = wintypes.DWORD
    adv.ConvertSecurityDescriptorToStringSecurityDescriptorW.argtypes = [
        wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD,
        ctypes.POINTER(wintypes.LPWSTR), wintypes.LPVOID]
    adv.ConvertSecurityDescriptorToStringSecurityDescriptorW.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [wintypes.LPVOID]
    descriptor, sddl = wintypes.LPVOID(), wintypes.LPWSTR()
    assert adv.GetNamedSecurityInfoW(str(target), 1, 4, None, None, None, None,
                                     ctypes.byref(descriptor)) == 0
    try:
        assert adv.ConvertSecurityDescriptorToStringSecurityDescriptorW(
            descriptor, 1, 4, ctypes.byref(sddl), None)
        assert sddl.value.startswith('D:P')
        assert sddl.value.count('(A;') == 1 and ';;;OW)' in sddl.value
    finally:
        if sddl:
            kernel.LocalFree(sddl)
        kernel.LocalFree(descriptor)


@pytest.mark.parametrize('name', ['../secret', '.netconverter/session.json', 'file:stream', ''])
def test_path_escape_and_streams_refused(tmp_path, name):
    with pytest.raises(WorkspaceError):
        secure_snapshot(Workspace(tmp_path), name)


def test_existing_alternate_stream_is_refused(tmp_path):
    base = tmp_path / 'file'
    base.write_bytes(b'base')
    Path(str(base) + ':stream').write_bytes(b'private stream')
    with pytest.raises(WorkspaceError):
        secure_snapshot(Workspace(tmp_path), 'file:stream')


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


def test_junction_and_destination_symlink_refused(tmp_path):
    import subprocess
    outside = tmp_path.parent / ('junction-outside-' + tmp_path.name)
    outside.mkdir()
    secret = outside / 'secret.cfg'
    secret.write_bytes(b'outside')
    junction = tmp_path / 'junction'
    made = subprocess.run(['cmd', '/c', 'mklink', '/J', str(junction), str(outside)],
                          capture_output=True, check=False)
    assert made.returncode == 0, 'Windows junction setup failed'
    with pytest.raises(WorkspaceError):
        secure_snapshot(Workspace(tmp_path), 'junction/secret.cfg')
    target = tmp_path / 'draft_1.revision-1.yaml'
    os.symlink(secret, target)
    with pytest.raises(WorkspaceError):
        publish(Workspace(tmp_path))
    assert secret.read_bytes() == b'outside'


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


def test_source_handle_denies_concurrent_replacement_and_write(tmp_path, monkeypatch):
    from netconverter_cli import windows_draft_io as windows
    source = tmp_path / 'source.cfg'
    source.write_bytes(b'original')
    original = windows._read
    def racing_read(handle, limit):
        with pytest.raises(PermissionError):
            source.write_bytes(b'changed')
        with pytest.raises(PermissionError):
            source.rename(tmp_path / 'moved.cfg')
        return original(handle, limit)
    monkeypatch.setattr(windows, '_read', racing_read)
    assert secure_snapshot(Workspace(tmp_path), 'source.cfg')[1] == b'original'


def test_held_workspace_cannot_be_renamed_during_publication(tmp_path, monkeypatch):
    from netconverter_cli import windows_draft_io as windows
    root = tmp_path / 'workspace'
    root.mkdir()
    workspace = Workspace(root)
    original = windows._rename
    def racing_rename(handle, directory, filename):
        with pytest.raises(PermissionError):
            root.rename(tmp_path / 'moved')
        return original(handle, directory, filename)
    monkeypatch.setattr(windows, '_rename', racing_rename)
    assert publish(workspace).read_bytes() == b'synthetic: true\n'
    assert not (tmp_path / 'moved').exists()


def test_failed_rename_removes_temporary_file(tmp_path, monkeypatch):
    from netconverter_cli import windows_draft_io as windows
    def fail_rename(*args):
        raise OSError(5, 'synthetic failure')
    monkeypatch.setattr(windows, '_rename', fail_rename)
    with pytest.raises(WorkspaceError):
        publish(Workspace(tmp_path))
    assert not list(tmp_path.glob('.nc-draft-*'))
    assert not (tmp_path / 'draft_1.revision-1.yaml').exists()


def test_unicode_workspace_and_input(tmp_path):
    root = tmp_path / '工程-🔒'
    root.mkdir()
    (root / '配置.cfg').write_bytes(b'hostname synthetic\n')
    workspace = Workspace(root)
    assert secure_snapshot(workspace, '配置.cfg')[1] == b'hostname synthetic\n'
    assert publish(workspace).read_bytes() == b'synthetic: true\n'
