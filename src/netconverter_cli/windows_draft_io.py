"""Windows guided file IO using held handles and no-replace publication.

Only local NTFS volumes are supported. Directory handles deny delete sharing
for the lifetime of each operation; reparse points are refused. This
module is imported only on Windows and never handles model-selected URLs.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import hashlib
import msvcrt
import os
from pathlib import Path
import stat
import uuid

from .workspace import WorkspaceError

_k = ctypes.WinDLL("kernel32", use_last_error=True)
_k.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                          wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
_k.CreateFileW.restype = wintypes.HANDLE
_k.CloseHandle.argtypes = [wintypes.HANDLE]
_k.CloseHandle.restype = wintypes.BOOL
_k.GetFileType.argtypes = [wintypes.HANDLE]
_k.GetFileType.restype = wintypes.DWORD
_k.GetFileInformationByHandleEx.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD]
_k.GetFileInformationByHandleEx.restype = wintypes.BOOL
_k.GetFinalPathNameByHandleW.argtypes = [wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD]
_k.GetFinalPathNameByHandleW.restype = wintypes.DWORD
_k.SetFileInformationByHandle.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD]
_k.SetFileInformationByHandle.restype = wintypes.BOOL
_k.GetDriveTypeW.argtypes = [wintypes.LPCWSTR]
_k.GetDriveTypeW.restype = wintypes.UINT
_k.GetVolumeInformationW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD,
                                     wintypes.LPVOID, wintypes.LPVOID, wintypes.LPVOID,
                                     wintypes.LPWSTR, wintypes.DWORD]
_k.GetVolumeInformationW.restype = wintypes.BOOL
_k.LocalFree.argtypes = [wintypes.HLOCAL]
_k.LocalFree.restype = wintypes.HLOCAL
_adv = ctypes.WinDLL("advapi32", use_last_error=True)
_adv.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
    wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(wintypes.LPVOID), wintypes.LPVOID]
_adv.ConvertStringSecurityDescriptorToSecurityDescriptorW.restype = wintypes.BOOL
_adv.GetSecurityInfo.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD,
    ctypes.POINTER(wintypes.LPVOID), wintypes.LPVOID, wintypes.LPVOID,
    wintypes.LPVOID, ctypes.POINTER(wintypes.LPVOID)]
_adv.GetSecurityInfo.restype = wintypes.DWORD
_adv.ConvertSecurityDescriptorToStringSecurityDescriptorW.argtypes = [
    wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD,
    ctypes.POINTER(wintypes.LPWSTR), wintypes.LPVOID]
_adv.ConvertSecurityDescriptorToStringSecurityDescriptorW.restype = wintypes.BOOL
_adv.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
_adv.OpenProcessToken.restype = wintypes.BOOL
_adv.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID,
    wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
_adv.GetTokenInformation.restype = wintypes.BOOL
_adv.EqualSid.argtypes = [wintypes.LPVOID, wintypes.LPVOID]
_adv.EqualSid.restype = wintypes.BOOL
_adv.ConvertSidToStringSidW.argtypes = [wintypes.LPVOID, ctypes.POINTER(wintypes.LPWSTR)]
_adv.ConvertSidToStringSidW.restype = wintypes.BOOL

_INVALID = ctypes.c_void_p(-1).value
_READ, _WRITE, _DELETE = 0x80000000, 0x40000000, 0x00010000
_SHARE_READ, _SHARE_WRITE = 1, 2
_OPEN_EXISTING, _CREATE_NEW = 3, 1
_OPEN_REPARSE, _BACKUP = 0x00200000, 0x02000000
_REPARSE, _DIRECTORY = 0x400, 0x10


class _Attributes(ctypes.Structure):
    _fields_ = [("attributes", wintypes.DWORD), ("tag", wintypes.DWORD)]


class _SecurityAttributes(ctypes.Structure):
    _fields_ = [("length", wintypes.DWORD), ("descriptor", wintypes.LPVOID),
                ("inherit", wintypes.BOOL)]


def _fail():
    raise WorkspaceError("Guided file could not be accessed securely")


def _current_user_sid_text() -> str:
    token, sid_text = wintypes.HANDLE(), wintypes.LPWSTR()
    try:
        if not _adv.OpenProcessToken(_k.GetCurrentProcess(), 8, ctypes.byref(token)):
            _fail()
        size = wintypes.DWORD()
        _adv.GetTokenInformation(token, 1, None, 0, ctypes.byref(size))
        if not size.value:
            _fail()
        info = ctypes.create_string_buffer(size.value)
        if not _adv.GetTokenInformation(token, 1, info, size.value, ctypes.byref(size)):
            _fail()
        user_sid = ctypes.cast(info, ctypes.POINTER(wintypes.LPVOID)).contents
        if not _adv.ConvertSidToStringSidW(user_sid, ctypes.byref(sid_text)):
            _fail()
        return sid_text.value
    finally:
        if sid_text:
            _k.LocalFree(sid_text)
        if token.value:
            _k.CloseHandle(token)


def _open(path: Path, access: int, disposition: int, directory: bool) -> int:
    descriptor = wintypes.LPVOID()
    security = None
    if disposition == _CREATE_NEW:
        # Protect the DACL against inherited workspace permissions. OW is the
        # Windows OWNER RIGHTS SID, so only the file owner has an allow ACE.
        if not _adv.ConvertStringSecurityDescriptorToSecurityDescriptorW(
                "O:" + _current_user_sid_text() + "D:P(A;;FA;;;OW)",
                1, ctypes.byref(descriptor), None):
            _fail()
        security = _SecurityAttributes(ctypes.sizeof(_SecurityAttributes), descriptor, False)
    try:
        # Parent directories must permit child creation/rename while denying
        # delete sharing, which pins the directory's own name against swaps.
        share = _SHARE_READ | (_SHARE_WRITE if directory else 0)
        handle = _k.CreateFileW(str(path), access, share,
                                ctypes.byref(security) if security is not None else None,
                                disposition, _OPEN_REPARSE | (_BACKUP if directory else 0), None)
    finally:
        if descriptor.value:
            _k.LocalFree(descriptor)
    if handle == _INVALID:
        raise OSError(ctypes.get_last_error(), "secure file open failed")
    attrs = _Attributes()
    if (not _k.GetFileInformationByHandleEx(handle, 9, ctypes.byref(attrs), ctypes.sizeof(attrs))
            or attrs.attributes & _REPARSE or bool(attrs.attributes & _DIRECTORY) != directory
            or _k.GetFileType(handle) != 1):
        _k.CloseHandle(handle)
        _fail()
    return handle


def _volume(root: Path) -> None:
    anchor = root.anchor
    if len(anchor) != 3 or anchor[1:] != ':\\' or _k.GetDriveTypeW(anchor) != 3:
        _fail()
    filesystem = ctypes.create_unicode_buffer(64)
    if not _k.GetVolumeInformationW(anchor, None, 0, None, None, None, filesystem, len(filesystem)):
        _fail()
    if filesystem.value.upper() != "NTFS":
        _fail()


def _directories(path: Path) -> list[int]:
    _volume(path)
    handles = []
    try:
        current = Path(path.anchor)
        # Read-data access participates in Windows share checks. Attribute-only
        # opens do not prevent an attacker from renaming the directory.
        handles.append(_open(current, _READ, _OPEN_EXISTING, True))
        for part in path.parts[1:]:
            if part in {".", ".."} or ":" in part:
                _fail()
            current /= part
            handles.append(_open(current, _READ, _OPEN_EXISTING, True))
        return handles
    except Exception:
        for handle in reversed(handles):
            _k.CloseHandle(handle)
        raise


def _read(handle: int, limit: int) -> bytes:
    # Duplicate so the original handle continues to pin the name and contents.
    process = _k.GetCurrentProcess()
    duplicate = wintypes.HANDLE()
    if not _k.DuplicateHandle(process, handle, process, ctypes.byref(duplicate), 0, False, 2):
        _fail()
    fd = msvcrt.open_osfhandle(duplicate.value, os.O_RDONLY | os.O_BINARY)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= limit:
            _fail()
        chunks, left = [], limit + 1
        while left:
            part = os.read(fd, min(left, 65536))
            if not part:
                break
            chunks.append(part)
            left -= len(part)
        data = b"".join(chunks)
        if len(data) != info.st_size or os.fstat(fd).st_size != info.st_size:
            _fail()
        return data
    finally:
        os.close(fd)


def _final_path(handle: int) -> Path:
    length = _k.GetFinalPathNameByHandleW(handle, None, 0, 0)
    if not 0 < length <= 32768:
        _fail()
    buffer = ctypes.create_unicode_buffer(length + 1)
    written = _k.GetFinalPathNameByHandleW(handle, buffer, len(buffer), 0)
    if not 0 < written < len(buffer):
        _fail()
    return Path(buffer.value)


def _protected_owner_acl(handle: int) -> bool:
    """Verify the held file's owner and exact protected DACL before reuse."""
    owner, descriptor, sddl = wintypes.LPVOID(), wintypes.LPVOID(), wintypes.LPWSTR()
    token = wintypes.HANDLE()
    try:
        # SE_FILE_OBJECT, OWNER_SECURITY_INFORMATION | DACL_SECURITY_INFORMATION.
        if _adv.GetSecurityInfo(handle, 1, 5, ctypes.byref(owner), None, None, None,
                                ctypes.byref(descriptor)) != 0 or not owner.value:
            return False
        if not _adv.ConvertSecurityDescriptorToStringSecurityDescriptorW(
                descriptor, 1, 4, ctypes.byref(sddl), None):
            return False
        if sddl.value != 'D:P(A;;FA;;;OW)':
            return False
        if not _adv.OpenProcessToken(_k.GetCurrentProcess(), 8, ctypes.byref(token)):
            return False
        size = wintypes.DWORD()
        _adv.GetTokenInformation(token, 1, None, 0, ctypes.byref(size))
        if not size.value:
            return False
        info = ctypes.create_string_buffer(size.value)
        if not _adv.GetTokenInformation(token, 1, info, size.value, ctypes.byref(size)):
            return False
        user_sid = ctypes.cast(info, ctypes.POINTER(wintypes.LPVOID)).contents
        return bool(_adv.EqualSid(owner, user_sid))
    finally:
        if token.value:
            _k.CloseHandle(token)
        if sddl:
            _k.LocalFree(sddl)
        if descriptor.value:
            _k.LocalFree(descriptor)


_k.GetCurrentProcess.restype = wintypes.HANDLE
_k.DuplicateHandle.argtypes = [wintypes.HANDLE, wintypes.HANDLE, wintypes.HANDLE,
                               ctypes.POINTER(wintypes.HANDLE), wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
_k.DuplicateHandle.restype = wintypes.BOOL


def snapshot(workspace, filename: str, max_bytes: int):
    if not isinstance(filename, str) or not filename or "\x00" in filename:
        raise WorkspaceError("Invalid draft input path")
    raw = Path(filename)
    components = raw.parts[1:] if raw.anchor else raw.parts
    if ".." in raw.parts or any(":" in p for p in components):
        raise WorkspaceError("Parent traversal or alternate streams are not accepted")
    candidate = raw if raw.is_absolute() else workspace.root / raw
    try:
        relative = candidate.relative_to(workspace.root)
    except ValueError:
        raise WorkspaceError("Path is outside the workspace") from None
    if not relative.parts or relative.parts[0].lower() == ".netconverter":
        raise WorkspaceError("Select a configuration outside the client state folder")
    handles, handle = [], None
    try:
        handles = _directories(candidate.parent)
        handle = _open(candidate, _READ, _OPEN_EXISTING, False)
        # Resolve 8.3 names through held handles before reading anything. A
        # lexical comparison alone lets NETCON~1 alias the client state folder.
        root_handle = handles[len(workspace.root.parts) - 1]
        state = _final_path(root_handle) / '.netconverter'
        if _final_path(handle).is_relative_to(state):
            _fail()
        data = _read(handle, max_bytes)
        if b"\x00" in data:
            _fail()
        data.decode("utf-8")
        return candidate, data, hashlib.sha256(data).hexdigest()
    except (OSError, UnicodeDecodeError, ValueError):
        raise WorkspaceError("Draft input could not be read securely") from None
    finally:
        if handle is not None:
            _k.CloseHandle(handle)
        for h in reversed(handles):
            _k.CloseHandle(h)


def _rename(handle: int, directory: int, filename: str) -> None:
    units = len(filename.encode("utf-16-le")) // 2
    class Rename(ctypes.Structure):
        _fields_ = [("replace", wintypes.BOOL), ("root", wintypes.HANDLE),
                    ("length", wintypes.DWORD), ("name", wintypes.WCHAR * (units + 1))]
    # SetFileInformationByHandle rejects a non-null RootDirectory on some
    # Windows versions. The absolute destination remains confined by the
    # held, no-delete-sharing handles for every ancestor.
    value = Rename(False, None, len(filename.encode("utf-16-le")), filename)
    if not _k.SetFileInformationByHandle(handle, 3, ctypes.byref(value), ctypes.sizeof(value)):
        raise OSError(ctypes.get_last_error(), "secure rename failed")


def publish(workspace, filename: str, content: bytes, sha256: str) -> Path:
    handles, handle, published = [], None, False
    temporary = workspace.root / (".nc-draft-" + uuid.uuid4().hex)
    destination = workspace.root / filename
    try:
        handles = _directories(workspace.root)
        try:
            existing = _open(destination, _READ, _OPEN_EXISTING, False)
        except OSError as exc:
            if exc.errno not in (2, 3):
                raise
        else:
            try:
                if not _protected_owner_acl(existing) or _read(existing, len(content)) != content:
                    _fail()
                return destination
            finally:
                _k.CloseHandle(existing)
        handle = _open(temporary, _READ | _WRITE | _DELETE, _CREATE_NEW, False)
        duplicate = wintypes.HANDLE()
        process = _k.GetCurrentProcess()
        if not _k.DuplicateHandle(process, handle, process, ctypes.byref(duplicate), 0, False, 2):
            _fail()
        fd = msvcrt.open_osfhandle(duplicate.value, os.O_WRONLY | os.O_BINARY)
        try:
            remaining = memoryview(content)
            while remaining:
                written = os.write(fd, remaining)
                if not written:
                    _fail()
                remaining = remaining[written:]
            os.fsync(fd)
        finally:
            os.close(fd)
        _rename(handle, handles[-1], str(destination))
        published = True
        # The data was validated before writing and the write handle has never
        # allowed a concurrent writer. A no-replace rename pins those bytes.
        return destination
    except (OSError, ValueError):
        raise WorkspaceError("Artifact could not be published securely without replacing a file") from None
    finally:
        if handle is not None:
            if not published:
                disposition = wintypes.BOOL(True)
                _k.SetFileInformationByHandle(handle, 4, ctypes.byref(disposition), ctypes.sizeof(disposition))
            _k.CloseHandle(handle)
        for h in reversed(handles):
            _k.CloseHandle(h)
