"""Downloading a validate or optimize job saves its result, not an empty report.

Reproduced on Windows 2026-10-19 (prod, jobs val_075a5e892d3d / opt_0064db2f1d52):
`download` saved only `<job>.report.json` with `report: null` and an empty
translation report, because GET /jobs/{id}/report carries conversion evidence
only. GET /jobs/{id} returns `job_type` and, once completed, the job's
`validation` or `optimization` result; that is what a download must keep.
"""
import json

import httpx
import pytest

from netconverter_cli.api import APIError, ExternalClient, StaticCredential
from netconverter_cli.backend import download_external
from netconverter_cli.workspace import Workspace

SERVER = "https://api.netconverter.ai/external/v1"
EMPTY_REPORT = {"job_id": "x", "status": "completed", "translation_status": None, "report": None,
                "translation_report": {"checkpoints": [], "evidence_available": False}}


def client_for(jobs, seen):
    def server(request):
        path = request.url.path.removeprefix("/external/v1/")
        seen.append(path)
        env = lambda data: httpx.Response(200, json={"success": True, "data": data})
        parts = path.split("/")
        job = jobs.get(parts[1]) if len(parts) > 1 else None
        if job is None:
            return httpx.Response(404, json={})
        if len(parts) == 2:
            return env(job)
        if parts[2] == "report":
            return env({**EMPTY_REPORT, "job_id": parts[1]})
        if parts[2] == "translated" and job.get("translated"):
            return httpx.Response(200, text=job["translated"])
        return httpx.Response(404, json={})
    return ExternalClient(StaticCredential("nck_synthetic"), SERVER, transport=httpx.MockTransport(server))


VALIDATION = {"finding_count": 5, "findings": [{"severity": "warning", "title": "synthetic"}]}
OPTIMIZATION = {"finding_count": 6, "severity_counts": {"low": 6}}


@pytest.mark.parametrize("job_id,job_type,key,result", [
    ("val_aaaaaaaaaaaa", "validate", "validation", VALIDATION),
    ("opt_bbbbbbbbbbbb", "optimize", "optimization", OPTIMIZATION),
])
def test_analysis_download_saves_the_result(tmp_path, job_id, job_type, key, result):
    seen = []
    jobs = {job_id: {"job_id": job_id, "job_type": job_type, "status": "completed", key: result}}
    client = client_for(jobs, seen)
    try:
        saved = download_external(client, job_id, Workspace(tmp_path))
    finally:
        client.close()
    names = sorted(p.name for p in saved)
    assert names == [f"{job_id}.{key}.json"]  # no empty report.json beside it
    data = json.loads(saved[0].read_text(encoding="utf-8"))
    assert data[key] == result
    assert data["job_type"] == job_type and data["job_id"] == job_id
    assert f"jobs/{job_id}/report" not in seen


def test_unfinished_analysis_job_says_so(tmp_path):
    jobs = {"val_cccccccccccc": {"job_id": "val_cccccccccccc", "job_type": "validate",
                                 "status": "processing", "validation": None}}
    client = client_for(jobs, [])
    try:
        with pytest.raises(APIError) as exc:
            download_external(client, "val_cccccccccccc", Workspace(tmp_path))
    finally:
        client.close()
    assert exc.value.code == "job_not_completed"
    assert not list(tmp_path.glob("val_*"))


def test_conversion_download_is_unchanged(tmp_path):
    jobs = {"tra_dddddddddddd": {"job_id": "tra_dddddddddddd", "job_type": "convert",
                                 "status": "completed", "translated": "<config/>\n"}}
    client = client_for(jobs, [])
    try:
        saved = download_external(client, "tra_dddddddddddd", Workspace(tmp_path))
    finally:
        client.close()
    assert sorted(p.name for p in saved) == ["tra_dddddddddddd.report.json", "tra_dddddddddddd.translated.txt"]
