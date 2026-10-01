import hashlib
import json
from pathlib import Path

import pytest

from netconverter_terminal.workspace import Workspace, WorkspaceError
from netconverter_terminal.privacy import model_summary, safe_prompt


def test_source_boundary_and_byte_limit(tmp_path):
    work = Workspace(tmp_path)
    source = tmp_path / "source.cfg"
    source.write_bytes(b"x" * 50_000)
    assert len(work.snapshot(source.name)[1]) == 50_000
    source.write_bytes(b"x" * 50_001)
    with pytest.raises(WorkspaceError):
        work.snapshot(source.name)
    with pytest.raises(WorkspaceError):
        work.snapshot("../outside.cfg")
    source.unlink()
    source.symlink_to(Path("/etc/hosts"))
    with pytest.raises(WorkspaceError):
        work.snapshot(source.name)


def test_artifacts_are_verified_and_never_overwrite(tmp_path):
    work = Workspace(tmp_path)
    data = b"synthetic artifact"
    digest = hashlib.sha256(data).hexdigest()
    destination = work.save_artifact("tra_123", "output.xml", data, digest)
    assert destination.read_bytes() == data
    assert work.save_artifact("tra_123", "output.xml", data, digest) == destination
    with pytest.raises(WorkspaceError):
        work.save_artifact("tra_123", "output.xml", b"changed", digest)
    with pytest.raises(WorkspaceError):
        work.save_artifact("tra_123", "../source.cfg", data, digest)
    destination.write_bytes(b"user edit")
    with pytest.raises(WorkspaceError):
        work.save_artifact("tra_123", "output.xml", data, digest)
    assert destination.read_bytes() == b"user edit"


def test_private_results_never_enter_model_summary():
    secret = "SYNTHETIC_PRIVATE_MARKER"
    result = {
        "status": "completed",
        "counts": {"unused": 2, secret: 99},
        "data": {"configuration": secret},
        "error": secret,
        "job_id": "tra_0123456789ab",
        "filename": secret,
        "model_summary": {"counts": {secret: 9}, "note": secret},
    }
    serialized = json.dumps(model_summary(result))
    assert secret not in serialized
    assert "completed" in serialized


def test_prompt_refuses_config_paste_and_abstracts_known_identifiers():
    secret = "SYNTHETIC_OBJECT_NAME"
    prompt, bindings = safe_prompt(
        f"Is tcp 80 open to {secret} at 192.0.2.8?", [secret]
    )
    assert secret not in prompt and "192.0.2.8" not in prompt
    assert secret in bindings.values() and "192.0.2.8" in bindings.values()
    with pytest.raises(ValueError):
        safe_prompt("object network PRIVATE\n host 192.0.2.8", [])
