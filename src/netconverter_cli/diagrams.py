"""Download a governed diagram recipe; never follow a model-supplied URL."""
from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class DiagramArtifact(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    kind: Literal['topology', 'comparison', 'traffic', 'nat', 'policy'] = 'topology'
    side: Literal['source', 'target'] = 'source'
    max_nodes: int = Field(default=60, ge=4, le=120)
    format: Literal['svg', 'png', 'pdf', 'drawio', 'json']
    view: Literal['default', 'strict'] = 'default'
    expected_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    flow: dict | None = None


def download_diagram(client, output, job_id, recipe, *, strict=False):
    artifact = DiagramArtifact.model_validate(recipe)
    if artifact.flow is not None and artifact.kind != 'traffic':
        raise ValueError('Flow inputs require a traffic diagram')
    if strict:
        artifact.view = 'strict'
        if artifact.flow is not None:
            raise ValueError('Explicit flow inputs are unavailable in strict view')
    content = client.diagram(job_id, artifact.model_dump(exclude_none=True))
    # Include immutable byte identity, preserving previous document revisions.
    filename = f'{artifact.kind}-{artifact.side}-{artifact.expected_sha256[:16]}.{artifact.format}'
    return output.save_artifact(job_id, filename, content, artifact.expected_sha256)
