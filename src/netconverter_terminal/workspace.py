"""Bounded local IO. This module is never exposed as a model tool."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

MAX_CONFIG_BYTES = 50_000
_IDENTIFIER = re.compile(r"[A-Za-z0-9_-]{1,80}\Z")


class WorkspaceError(ValueError):
    pass


class Workspace:
    def __init__(self, root: Path | str):
        self.root = Path(root).resolve(strict=True)
        self.state_dir = self.root / ".netconverter"

    def _inside(self, path: Path) -> Path:
        resolved = path.resolve()
        if not resolved.is_relative_to(self.root):
            raise WorkspaceError("Path is outside the workspace")
        return resolved

    def snapshot(self, filename: str) -> tuple[Path, bytes, str]:
        path = self._inside(self.root / filename)
        if not path.is_file() or path.is_symlink():
            raise WorkspaceError("Select a regular configuration file")
        # Bound the read, including when the source changes during the read.
        with path.open("rb") as stream:
            content = stream.read(MAX_CONFIG_BYTES + 1)
        if not content or len(content) > MAX_CONFIG_BYTES:
            raise WorkspaceError(
                "Free pilot inputs must be 1–50,000 bytes; contact NetConverter for larger files"
            )
        try:
            content.decode("utf-8")
        except UnicodeDecodeError:
            raise WorkspaceError(
                "Select a UTF-8 text, SET, or XML configuration"
            ) from None
        if b"\x00" in content:
            raise WorkspaceError("Binary configurations are not supported")
        return path, content, hashlib.sha256(content).hexdigest()

    def load(self) -> dict:
        path = self._inside(self.state_dir / "session.json")
        if not path.exists():
            return {"version": 1, "configurations": {}, "jobs": {}}
        if path.stat().st_size > 1_000_000:
            raise WorkspaceError("Session metadata exceeds its limit")
        try:
            state = json.loads(path.read_text())
            if state.get("version") != 1 or not isinstance(state.get("jobs"), dict):
                raise ValueError()
            return state
        except (ValueError, TypeError):
            raise WorkspaceError(
                "Invalid session metadata; originals have not been changed"
            ) from None

    def store(self, state: dict) -> None:
        self._inside(self.state_dir).mkdir(mode=0o700, exist_ok=True)
        self._atomic_replace(
            self.state_dir / "session.json", json.dumps(state, indent=2).encode()
        )

    @staticmethod
    def _atomic_replace(path: Path, content: bytes) -> None:
        fd, name = tempfile.mkstemp(prefix=".nc-", dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, path)
        finally:
            Path(name).unlink(missing_ok=True)

    def save_artifact(
        self, job_id: str, filename: str, content: bytes, sha256: str
    ) -> Path:
        if not _IDENTIFIER.fullmatch(job_id):
            raise WorkspaceError("Invalid server job ID")
        if (
            not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,120}", filename)
            or ".." in filename
        ):
            raise WorkspaceError("Invalid artifact filename")
        if (
            not re.fullmatch(r"[a-f0-9]{64}", sha256)
            or hashlib.sha256(content).hexdigest() != sha256
        ):
            raise WorkspaceError("Artifact checksum failed; no file was written")
        path = self.root / f"{job_id}.{filename}"
        if path.is_symlink():
            raise WorkspaceError("Artifact destination is a symlink")
        if path.exists():
            if path.read_bytes() == content:
                return path
            raise WorkspaceError(
                "Artifact destination already exists with different contents"
            )
        fd, temporary = tempfile.mkstemp(prefix=".nc-download-", dir=self.root)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            # Atomic no-clobber publication, including a concurrent user write.
            try:
                os.link(temporary, path)
            except FileExistsError:
                raise WorkspaceError(
                    "Artifact destination was created during download"
                ) from None
        finally:
            Path(temporary).unlink(missing_ok=True)
        return path
