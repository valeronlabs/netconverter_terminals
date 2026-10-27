"""Descriptor-confined input snapshots for the opt-in draft workflow.

POSIX no-follow descriptor traversal is required. Unsupported platforms refuse
new draft imports rather than weakening this boundary to a check-then-open path.
Legacy Workspace behavior is intentionally unaffected.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import stat
import uuid

from .workspace import MAX_CONFIG_BYTES, Workspace, WorkspaceError

MAX_DOCUMENT_BYTES = 1_000_000
MAX_ARTIFACT_BYTES = 32 * 1024 * 1024


def secure_publish(workspace: Workspace, draft_id: str, revision: int, content: bytes, sha256: str) -> Path:
    if (not isinstance(draft_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", draft_id) or
            type(revision) is not int or revision <= 0):
        raise WorkspaceError("Invalid draft artifact")
    return secure_publish_file(workspace, f"{draft_id}.revision-{revision}.yaml", content, sha256,
                               max_bytes=MAX_DOCUMENT_BYTES)


def secure_publish_file(workspace: Workspace, filename: str, content: bytes, sha256: str, *, max_bytes: int) -> Path:
    """Publish verified bytes through held no-follow directory descriptors.

    Existing regular files are compared through a bounded descriptor read.
    Atomic hard-link publication never overwrites a destination. A moved root
    fails closed and temporary bytes are removed using the held descriptor.
    """
    if (not isinstance(filename, str) or not re.fullmatch(r"[A-Za-z0-9_-][A-Za-z0-9._-]{0,200}", filename) or
            ".." in filename or type(max_bytes) is not int or not 0 < max_bytes <= MAX_ARTIFACT_BYTES or
            not isinstance(content, bytes) or not 0 < len(content) <= max_bytes or not isinstance(sha256, str) or
            not re.fullmatch(r"[a-f0-9]{64}", sha256) or hashlib.sha256(content).hexdigest() != sha256):
        raise WorkspaceError("Invalid draft artifact")
    if os.name == "nt":
        from .windows_draft_io import publish
        return publish(workspace, filename, content, sha256)
    if (os.name != "posix" or not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_DIRECTORY") or
            any(fn not in os.supports_dir_fd for fn in (os.open, os.stat, os.link, os.unlink))):
        raise WorkspaceError("Secure draft file access is unavailable on this platform")
    descriptors, links = [], []
    temporary = None
    published = False
    root_fd = None
    artifact_fd = None

    def verify_root():
        for parent, name, child in links:
            current, opened = os.stat(name, dir_fd=parent, follow_symlinks=False), os.fstat(child)
            if (current.st_dev, current.st_ino) != (opened.st_dev, opened.st_ino):
                raise WorkspaceError("The artifact workspace changed during publication")

    def identical_existing():
        fd = os.open(filename, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=root_fd)
        try:
            before = os.fstat(fd)
            if not stat.S_ISREG(before.st_mode) or before.st_size != len(content):
                raise WorkspaceError("Artifact destination already exists with different contents")
            chunks, remaining = [], len(content) + 1
            while remaining:
                chunk = os.read(fd, min(65_536, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            after = os.fstat(fd)
            current = os.stat(filename, dir_fd=root_fd, follow_symlinks=False)
            identity = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
            existing = b"".join(chunks)
            if (identity(before) != identity(after) or identity(current) != identity(after) or
                    existing != content or hashlib.sha256(existing).hexdigest() != sha256):
                raise WorkspaceError("Artifact destination changed or has different contents")
            verify_root()
            return workspace.root / filename
        finally:
            os.close(fd)

    try:
        root_fd = os.open(workspace.root.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        descriptors.append(root_fd)
        for part in workspace.root.parts[1:]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root_fd)
            descriptors.append(child)
            links.append((root_fd, part, child))
            root_fd = child
        verify_root()
        try:
            return identical_existing()
        except FileNotFoundError:
            pass
        temporary = ".nc-draft-" + uuid.uuid4().hex
        artifact_fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                              mode=0o600, dir_fd=root_fd)
        descriptors.append(artifact_fd)
        verify_root()
        remaining = memoryview(content)
        while remaining:
            written = os.write(artifact_fd, remaining)
            if not written:
                raise WorkspaceError("Artifact write did not complete")
            remaining = remaining[written:]
        os.fsync(artifact_fd)
        verify_root()
        try:
            os.link(temporary, filename, src_dir_fd=root_fd, dst_dir_fd=root_fd, follow_symlinks=False)
        except FileExistsError:
            return identical_existing()
        published = True
        verify_root()
        current, ours = os.stat(filename, dir_fd=root_fd, follow_symlinks=False), os.fstat(artifact_fd)
        if not stat.S_ISREG(current.st_mode) or (current.st_dev, current.st_ino) != (ours.st_dev, ours.st_ino):
            raise WorkspaceError("Artifact destination was replaced during publication")
        # The hard-link source is a name on POSIX. Check the destination against
        # the held file descriptor and re-read its bounded bytes after linking.
        identical_existing()
        current = os.stat(filename, dir_fd=root_fd, follow_symlinks=False)
        if (current.st_dev, current.st_ino) != (ours.st_dev, ours.st_ino):
            raise WorkspaceError("Artifact destination changed after publication")
        os.fsync(root_fd)
        return workspace.root / filename
    except (OSError, WorkspaceError):
        if published and artifact_fd is not None:
            try:
                current, ours = os.stat(filename, dir_fd=root_fd, follow_symlinks=False), os.fstat(artifact_fd)
                if (current.st_dev, current.st_ino) == (ours.st_dev, ours.st_ino):
                    os.unlink(filename, dir_fd=root_fd)
            except OSError:
                pass
        raise WorkspaceError("Artifact could not be published securely without replacing a file") from None
    finally:
        if temporary is not None and root_fd is not None:
            try:
                current = os.stat(temporary, dir_fd=root_fd, follow_symlinks=False)
                ours = os.fstat(artifact_fd) if artifact_fd is not None else None
                if ours is not None and (current.st_dev, current.st_ino) == (ours.st_dev, ours.st_ino):
                    os.unlink(temporary, dir_fd=root_fd)
            except OSError:
                pass
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def secure_snapshot(workspace: Workspace, filename: str, max_bytes: int = MAX_CONFIG_BYTES) -> tuple[Path, bytes, str]:
    if os.name == "nt":
        from .windows_draft_io import snapshot
        return snapshot(workspace, filename, max_bytes)
    if (os.name != "posix" or not hasattr(os, "O_NOFOLLOW") or
            not hasattr(os, "O_DIRECTORY") or os.open not in os.supports_dir_fd or
            os.stat not in os.supports_dir_fd):
        raise WorkspaceError("Secure draft file access is unavailable on this platform")
    if not isinstance(filename, str) or not filename or "\x00" in filename:
        raise WorkspaceError("Invalid draft input path")
    raw = Path(filename)
    if ".." in raw.parts:
        raise WorkspaceError("Parent traversal is not accepted")
    candidate = raw if raw.is_absolute() else workspace.root / raw
    try:
        relative = candidate.relative_to(workspace.root)
    except ValueError:
        raise WorkspaceError("Path is outside the workspace") from None
    if not relative.parts or relative.parts[0] == ".netconverter":
        raise WorkspaceError("Select a configuration outside the client state folder")
    parts = candidate.parts[1:]
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    descriptors: list[int] = []
    links: list[tuple[int, str, int]] = []
    try:
        parent = os.open(candidate.anchor, directory_flags)
        descriptors.append(parent)
        for part in parts[:-1]:
            child = os.open(part, directory_flags, dir_fd=parent)
            descriptors.append(child)
            links.append((parent, part, child))
            parent = child
        fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        descriptors.append(fd)
        links.append((parent, parts[-1], fd))
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= max_bytes:
            raise WorkspaceError("Select a regular nonempty file within the draft input limit")
        chunks, remaining = [], max_bytes + 1
        while remaining:
            chunk = os.read(fd, min(65_536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        content = b"".join(chunks)
        after = os.fstat(fd)
        identity = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
        if identity(before) != identity(after) or len(content) != before.st_size:
            raise WorkspaceError("The input changed while it was being read")
        for parent_fd, name, child_fd in links:
            current = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
            opened = os.fstat(child_fd)
            if (current.st_dev, current.st_ino) != (opened.st_dev, opened.st_ino):
                raise WorkspaceError("The input path changed while it was being read")
        if not content or len(content) > max_bytes or b"\x00" in content:
            raise WorkspaceError("Select bounded UTF-8 configuration text")
        try:
            content.decode("utf-8")
        except UnicodeDecodeError:
            raise WorkspaceError("Select UTF-8 configuration text") from None
        return candidate, content, hashlib.sha256(content).hexdigest()
    except OSError:
        raise WorkspaceError("Draft input could not be read securely") from None
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)
