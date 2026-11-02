"""Synthetic diagram download contract; no claim of live-server verification."""
import hashlib
import json

import httpx
import pytest

from netconverter_cli.api import ExternalClient, StaticCredential
from netconverter_cli.diagrams import download_diagram
from netconverter_cli.mcp_server import Bridge, REMOTE_TOOLS_DEFAULT, REMOTE_TOOLS_STRICT
from netconverter_cli.workspace import Workspace, WorkspaceError

CONTENT = b'<svg xmlns="http://www.w3.org/2000/svg"><text>synthetic</text></svg>'
HASH = hashlib.sha256(CONTENT).hexdigest()
RECIPE = {'format': 'svg', 'kind': 'topology', 'side': 'source', 'expected_sha256': HASH}


def test_download_fixed_route_bearer_hash_and_immutable_revision(tmp_path):
    requests = []
    def handle(request):
        requests.append(request)
        return httpx.Response(200, content=CONTENT)
    client = ExternalClient(StaticCredential('synthetic'), 'https://api.example/external/v1',
                            transport=httpx.MockTransport(handle))
    try:
        path = download_diagram(client, Workspace(tmp_path), 'job-synthetic', RECIPE)
        assert path.read_bytes() == CONTENT
        assert HASH[:16] in path.name
        assert requests[0].url.path == '/external/v1/jobs/job-synthetic/diagrams/render'
        assert requests[0].headers['Authorization'] == 'Bearer synthetic'
        assert download_diagram(client, Workspace(tmp_path), 'job-synthetic', RECIPE) == path
        with pytest.raises(WorkspaceError, match='checksum'):
            download_diagram(client, Workspace(tmp_path), 'job-synthetic', {**RECIPE, 'expected_sha256': '0'*64})
        assert len(list(tmp_path.iterdir())) == 1
    finally:
        client.close()


def test_strict_clamps_download_view_and_disallows_flow(tmp_path):
    requests = []
    def handle(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, content=CONTENT)
    client = ExternalClient('synthetic', 'https://api.example/external/v1', transport=httpx.MockTransport(handle))
    try:
        download_diagram(client, Workspace(tmp_path), 'job-synthetic', RECIPE, strict=True)
        assert requests[0]['view'] == 'strict'
        with pytest.raises(ValueError):
            download_diagram(client, Workspace(tmp_path), 'job-synthetic',
                             {**RECIPE, 'kind': 'traffic', 'flow': {'source_ip': '192.0.2.1'}}, strict=True)
        assert len(requests) == 1
    finally:
        client.close()


@pytest.mark.parametrize('extra', [{'url': 'https://evil.example'}, {'download_path': '//evil.example'},
                                  {'format': '../json'}, {'max_nodes': 10000}, {'max_nodes': True}])
def test_bad_recipe_never_calls_network(tmp_path, extra):
    class Offline:
        def diagram(self, *args):
            pytest.fail('Invalid recipe reached network')
    with pytest.raises(ValueError):
        download_diagram(Offline(), Workspace(tmp_path), 'synthetic', {**RECIPE, **extra})


def test_bridge_downloads_file_without_exposing_bytes(tmp_path):
    def handle(request):
        if request.url.path.endswith('/me'):
            return httpx.Response(200, json={'success': True, 'data': {'job_types': ['convert']}})
        assert request.url.path.endswith('/diagrams/render')
        return httpx.Response(200, content=CONTENT)
    bridge = Bridge(tmp_path, 'https://api.example/external/v1', StaticCredential('synthetic'),
                    transport=httpx.MockTransport(handle))
    result = bridge.call('download', {'job_id': 'job-synthetic', 'diagram': RECIPE})
    assert result.get('isError') is False
    assert '<svg' not in json.dumps(result)
    assert HASH in json.dumps(result)
    assert 'get_diagram' in REMOTE_TOOLS_DEFAULT & REMOTE_TOOLS_STRICT
