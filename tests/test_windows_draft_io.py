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
        assert sddl.value == 'D:P(A;;FA;;;OW)'
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


def test_client_state_short_name_alias_is_not_read(tmp_path):
    import ctypes
    from ctypes import wintypes
    state = tmp_path / '.netconverter'
    state.mkdir()
    (state / 'secret.cfg').write_text('synthetic')
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.GetShortPathNameW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD]
    kernel.GetShortPathNameW.restype = wintypes.DWORD
    buf = ctypes.create_unicode_buffer(32768)
    if not kernel.GetShortPathNameW(str(state), buf, len(buf)):
        pytest.skip('short names are not available on this volume')
    alias = Path(buf.value).name
    if alias.casefold() == state.name.casefold():
        pytest.skip('8.3 short names are disabled for this directory')
    with pytest.raises(WorkspaceError):
        secure_snapshot(Workspace(tmp_path), str(Path(alias) / 'secret.cfg'))


def test_client_state_hard_link_is_not_read(tmp_path):
    state = tmp_path / '.netconverter'
    state.mkdir()
    secret = state / 'session.json'
    secret.write_text('synthetic secret')
    os.link(secret, tmp_path / 'alias.cfg')
    with pytest.raises(WorkspaceError):
        secure_snapshot(Workspace(tmp_path), 'alias.cfg')


def test_external_hard_link_is_not_read(tmp_path):
    secret = tmp_path.parent / (tmp_path.name + '-outside.cfg')
    secret.write_text('synthetic external file')
    os.link(secret, tmp_path / 'alias.cfg')
    with pytest.raises(WorkspaceError):
        secure_snapshot(Workspace(tmp_path), 'alias.cfg')


def test_link_count_query_failure_is_closed(tmp_path, monkeypatch):
    from netconverter_cli import windows_draft_io as windows
    (tmp_path / 'source.cfg').write_text('synthetic')
    original = windows._k.GetFileInformationByHandleEx
    def query(handle, info_class, output, size):
        return False if info_class == 1 else original(handle, info_class, output, size)
    monkeypatch.setattr(windows._k, 'GetFileInformationByHandleEx', query)
    with pytest.raises(WorkspaceError):
        secure_snapshot(Workspace(tmp_path), 'source.cfg')


def test_hard_link_creation_and_unlink_blocked_while_snapshot_open(tmp_path, monkeypatch):
    from netconverter_cli import windows_draft_io as windows
    source = tmp_path / 'source.cfg'
    source.write_text('synthetic')
    original = windows._read
    def attempt_links(handle, limit):
        with pytest.raises(OSError):
            os.link(source, tmp_path / 'racing.cfg')
        with pytest.raises(OSError):
            source.unlink()
        return original(handle, limit)
    monkeypatch.setattr(windows, '_read', attempt_links)
    assert secure_snapshot(Workspace(tmp_path), 'source.cfg')[1] == b'synthetic'


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


def test_workspace_pinned_before_source_file_is_opened(tmp_path, monkeypatch):
    from netconverter_cli import windows_draft_io as windows
    root = tmp_path / 'workspace'
    root.mkdir()
    source = root / 'source.cfg'
    source.write_bytes(b'original')
    workspace = Workspace(root)
    original = windows._open
    def racing_open(path, access, disposition, directory):
        if path == source and not directory:
            with pytest.raises(PermissionError):
                root.rename(tmp_path / 'moved')
        return original(path, access, disposition, directory)
    monkeypatch.setattr(windows, '_open', racing_open)
    assert secure_snapshot(workspace, 'source.cfg')[1] == b'original'


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


@pytest.mark.parametrize('operation', ['snapshot', 'publish'])
def test_failed_crt_conversion_closes_duplicate_and_allows_cleanup(tmp_path, monkeypatch, operation):
    import ctypes
    from ctypes import wintypes
    from netconverter_cli import windows_draft_io as windows
    source = tmp_path / 'source.cfg'
    source.write_bytes(b'synthetic')
    captured = []
    def fail_conversion(handle, flags):
        captured.append(handle)
        raise OSError('synthetic CRT exhaustion')
    monkeypatch.setattr(windows.msvcrt, 'open_osfhandle', fail_conversion)
    with pytest.raises(WorkspaceError):
        if operation == 'snapshot':
            secure_snapshot(Workspace(tmp_path), 'source.cfg')
        else:
            publish(Workspace(tmp_path))
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.GetHandleInformation.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel.GetHandleInformation.restype = wintypes.BOOL
    assert captured and not kernel.GetHandleInformation(captured[0], ctypes.byref(wintypes.DWORD()))
    assert not list(tmp_path.glob('.nc-draft-*'))
    source.rename(tmp_path / 'moved.cfg')


def test_unicode_workspace_and_input(tmp_path):
    root = tmp_path / '工程-🔒'
    root.mkdir()
    (root / '配置.cfg').write_bytes(b'hostname synthetic\n')
    workspace = Workspace(root)
    assert secure_snapshot(workspace, '配置.cfg')[1] == b'hostname synthetic\n'
    assert publish(workspace).read_bytes() == b'synthetic: true\n'
