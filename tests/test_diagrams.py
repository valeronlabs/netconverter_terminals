"""Synthetic diagram download contract; no claim of live-server verification."""
import hashlib
import base64
import io
import json
import struct
import zlib

import httpx
import jsonschema
import pytest

from netconverter_cli.api import ExternalClient, StaticCredential
from netconverter_cli.diagrams import MAX_PREVIEW_BYTES, download_diagram
from netconverter_cli.mcp_server import (Bridge, PROTOCOL_VERSIONS, REMOTE_TOOLS_DEFAULT,
                                       REMOTE_TOOLS_STRICT, StdioServer)
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


def test_explicit_png_preview_protocol_and_refusals(tmp_path):
    """Frozen synthetic PNG: native content, view/hash binding, no file/URL bypass."""
    def chunk(kind, data):
        return (struct.pack('>I', len(data)) + kind + data
                + struct.pack('>I', zlib.crc32(kind + data)))

    png = (b'\x89PNG\r\n\x1a\n'
           + chunk(b'IHDR', struct.pack('>IIBBBBB', 1, 1, 8, 2, 0, 0, 0))
           + chunk(b'IDAT', zlib.compress(b'\x00\x00\x00\x00')) + chunk(b'IEND', b''))
    recipe = {'format': 'png', 'expected_sha256': hashlib.sha256(png).hexdigest()}
    requests = []
    body, status = png, 200

    def handle(request):
        requests.append(request)
        if request.url.path.endswith('/me'):
            return httpx.Response(200, json={'success': True, 'data': {'job_types': ['convert']}})
        assert request.url.path == '/external/v1/jobs/job-synthetic/diagrams/render'
        assert request.headers['Authorization'] == 'Bearer synthetic'
        return httpx.Response(status, content=body, headers={'Location': 'https://evil.example/x'})

    bridge = Bridge(tmp_path, 'https://api.example/external/v1', StaticCredential('synthetic'),
                    transport=httpx.MockTransport(handle))
    args = {'job_id': 'job-synthetic', 'diagram': recipe}
    # Exercise serialized stdio initialize/list/call for every supported protocol version.
    for protocol in PROTOCOL_VERSIONS:
        messages = [
            {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize',
             'params': {'protocolVersion': protocol, 'capabilities': {}}},
            {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'},
            {'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call',
             'params': {'name': 'preview_diagram', 'arguments': args}},
        ]
        out = io.StringIO()
        StdioServer(bridge).serve(io.StringIO('\n'.join(map(json.dumps, messages)) + '\n'), out)
        replies = [json.loads(line)['result'] for line in out.getvalue().splitlines()]
        assert replies[0]['protocolVersion'] == protocol
        descriptor = next(t for t in replies[1]['tools'] if t['name'] == 'preview_diagram')
        jsonschema.validate(args, descriptor['inputSchema'])
        result = replies[2]
        assert result['isError'] is False
        assert [item['type'] for item in result['content']] == ['text', 'image']
        block = result['content'][1]
        assert block['mimeType'] == 'image/png'
        assert base64.b64decode(block['data'], validate=True) == png
        assert result['structuredContent']['sha256'] == recipe['expected_sha256']
        assert result['structuredContent']['width'] == result['structuredContent']['height'] == 1
        assert json.loads(result['content'][0]['text']) == result['structuredContent']
        jsonschema.validate(result['structuredContent'], descriptor['outputSchema'])
        assert block['data'] not in json.dumps(result['structuredContent'])

    # Logs hold receipts only; previews do not read or save workspace artifacts.
    assert list(tmp_path.glob('*.png')) == []
    assert base64.b64encode(png).decode() not in (bridge.workspace.state_dir / 'bridge.jsonl').read_text()
    downloaded = bridge.call('download', args)
    assert downloaded['isError'] is False
    assert [item['type'] for item in downloaded['content']] == ['text']
    assert len(downloaded['structuredContent']['files']) == 1

    def refused(arguments=args, client=bridge):
        result = client.call('preview_diagram', arguments)
        assert result['isError'] is True, result
        assert all(item['type'] == 'text' for item in result['content'])
        return json.loads(result['content'][0]['text'])['error']

    assert refused({**args, 'diagram': {**recipe, 'expected_sha256': '0' * 64}}) == 'preview_refused'
    for invalid in ({**args, 'path': 'local.png'}, {**args, 'url': 'https://evil.example'},
                    {**args, 'job_id': '../escape'},
                    *({**args, 'diagram': {**recipe, **bad}} for bad in (
                        {'format': 'svg'}, {'url': 'https://evil.example'}, {'max_nodes': True},
                        {'flow': {'source_ip': '192.0.2.1'}}))):
        before = len(requests)
        assert refused(invalid) == 'invalid_arguments'
        assert len(requests) == before

    for level in ('masked', 'selected'):
        strict = Bridge(tmp_path, bridge.server, bridge.rest_credential, level=level,
                        transport=httpx.MockTransport(handle))
        result = strict.call('preview_diagram', args)
        assert result['isError'] is False
        assert result['structuredContent']['view'] == 'strict'
        assert json.loads(requests[-1].content)['view'] == 'strict'
        before = len(requests)
        assert refused({**args, 'diagram': {**recipe, 'kind': 'traffic', 'flow': {}}}, strict) == 'invalid_arguments'
        assert len(requests) == before
        # A hash from another projection cannot authorize the strict image.
        assert refused({**args, 'diagram': {**recipe, 'expected_sha256': '1' * 64}}, strict) == 'preview_refused'

    none = Bridge(tmp_path, bridge.server, bridge.rest_credential, level='none',
                  transport=httpx.MockTransport(handle))
    before = len(requests)
    assert refused(client=none) == 'level_none'
    assert len(requests) == before
    quick = Bridge(tmp_path, bridge.server, bridge.rest_credential, transport=httpx.MockTransport(handle))
    quick._profile = ('quick', frozenset())
    assert refused(client=quick) == 'unsupported_capability'
    assert len(requests) == before
    for status in (302, 403, 409):
        assert refused()
        assert len(requests) == before + 1  # redirects and error responses never become images
        before = len(requests)
    status = 200
    for body in (b'<svg/>', png[:20], png[:16] + struct.pack('>II', 5000, 1) + png[24:],
                 png[:16] + struct.pack('>II', 3000, 3000) + png[24:], png + b'x' * MAX_PREVIEW_BYTES):
        assert refused({**args, 'diagram': {**recipe, 'expected_sha256': hashlib.sha256(body).hexdigest()}})

    # A streamed oversized response is stopped at the bound, not fully buffered.
    class Oversized(httpx.SyncByteStream):
        count = 0
        def __iter__(self):
            for _ in range(100):
                self.count += 1
                yield b'x' * 65536
    stream = Oversized()
    bounded = Bridge(tmp_path, bridge.server, bridge.rest_credential,
                     transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=stream)))
    bounded._profile = ('external', frozenset())
    assert refused(client=bounded) == 'diagram_too_large'
    assert stream.count == MAX_PREVIEW_BYTES // 65536 + 1
