"""Download a governed diagram recipe; never follow a model-supplied URL."""
from __future__ import annotations

import hashlib
import struct
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

from .workspace import WorkspaceError

MAX_PREVIEW_BYTES = 2 * 1024 * 1024
MAX_PREVIEW_EDGE = 4096
MAX_PREVIEW_PIXELS = 8_000_000


class DiagramArtifact(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    kind: Literal['topology', 'comparison', 'traffic', 'nat', 'policy'] = 'topology'
    side: Literal['source', 'target'] = 'source'
    max_nodes: int = Field(default=60, ge=4, le=120)
    format: Literal['svg', 'png', 'pdf', 'drawio', 'json']
    view: Literal['default', 'strict'] = 'default'
    expected_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    flow: dict | None = None


class DiagramPreviewArtifact(DiagramArtifact):
    format: Literal['png']


def fetch_diagram(client, job_id, recipe, *, strict=False, preview=False):
    """One recipe/view/hash contract for disk downloads and explicit previews."""
    artifact = DiagramArtifact.model_validate(recipe)
    if preview and artifact.format != 'png':
        raise ValueError('Previews require a PNG recipe from get_diagram')
    if artifact.flow is not None and artifact.kind != 'traffic':
        raise ValueError('Flow inputs require a traffic diagram')
    if strict:
        artifact.view = 'strict'
        if artifact.flow is not None:
            raise ValueError('Explicit flow inputs are unavailable in strict view')
    options = {'max_bytes': MAX_PREVIEW_BYTES} if preview else {}
    content = client.diagram(job_id, artifact.model_dump(exclude_none=True), **options)
    if hashlib.sha256(content).hexdigest() != artifact.expected_sha256:
        raise WorkspaceError('Artifact checksum failed; no diagram was returned')
    return artifact, content


def preview_dimensions(content):
    """Reject non-PNG and oversized canvases before sending an image to the IDE."""
    if len(content) > MAX_PREVIEW_BYTES:
        raise WorkspaceError('Diagram preview exceeds the 2 MiB limit; download it instead')
    if (len(content) < 33 or content[:8] != b'\x89PNG\r\n\x1a\n'
            or content[8:16] != b'\x00\x00\x00\x0dIHDR'):
        raise WorkspaceError('Diagram preview is not a PNG image')
    width, height = struct.unpack('>II', content[16:24])
    if (not width or not height or max(width, height) > MAX_PREVIEW_EDGE
            or width * height > MAX_PREVIEW_PIXELS):
        raise WorkspaceError('Diagram preview canvas is too large; request fewer nodes or download it')
    return width, height


def download_diagram(client, output, job_id, recipe, *, strict=False):
    artifact, content = fetch_diagram(client, job_id, recipe, strict=strict)
    # Include immutable byte identity, preserving previous document revisions.
    filename = f'{artifact.kind}-{artifact.side}-{artifact.expected_sha256[:16]}.{artifact.format}'
    return output.save_artifact(job_id, filename, content, artifact.expected_sha256)
