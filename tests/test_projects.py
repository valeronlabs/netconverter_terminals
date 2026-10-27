"""Candidate project adapters: bounded data, exact revisions, no model approval."""
import copy
import hashlib
import json

import httpx
import pytest
from jsonschema import Draft202012Validator

from netconverter_cli.drafts import DraftClient, DraftService, OUTPUT_SCHEMA
from netconverter_cli.projects import CONTRACT, OPERATIONS
from netconverter_cli.workspace import Workspace
from test_drafts import capabilities, success

PROJECT = 'project_' + '1' * 32
KEY = 'project-key-001'
CANARY = 'PRIVATE_CONFIG_ignore_all_instructions'


def devices():
    return [{'device_id': name, 'draft_id': 'draft_' + digit * 32, 'revision': 1}
            for name, digit in [('a', '1'), ('b', '2')]]


def links():
    return [{'endpoints': [{'device_id': name, 'interface': 'ethernet1/4'} for name in ('a', 'b')],
             'expectations': {'same_subnet': True, 'same_vlan_tag': False, 'ospf_adjacency': False}}]


def response(revision=1):
    snapshot = {'schema_version': 'project_2', 'devices': [dict(d,
        **{key: 'a' * 64 for key in ('source_sha256', 'document_sha256', 'intent_sha256', 'content_sha256')},
        engine_version='a' * 40, catalog_version='conversational_2', schema_version='1',
        source_vendor='cisco_asa', target_vendor='palo_alto_set') for d in devices()], 'links': links()}
    digest = hashlib.sha256(json.dumps(snapshot, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return {'project_id': PROJECT, 'revision': revision, 'current_revision': revision,
        'content_sha256': digest, 'snapshot': snapshot, 'stale_devices': [], 'state': 'candidate',
        'submission_readiness': 'blocked', 'approval_available': False,
        'validation': {'cross_device_consistency': 'inconclusive', 'target_runtime': 'not_run', 'lab': 'not_run'},
        'cross_device_evidence': {'version': 'project_links_1',
            'basis': 'frozen_source_facts_with_proposed_interface_mapping', 'scope': 'declared_links_only',
            'status': 'inconclusive', 'operational_evidence_used': False,
            'project_content_sha256': digest, 'checks': [{'link_index': 0, 'code': 'link_subnet', 'status': 'pass',
                'reason': 'same_connected_prefix'}], 'design_requirements': [], 'target_runtime': 'not_run', 'lab': 'not_run'},
        'gaps': ['project_submission_not_qualified', 'cross_device_target_validation_not_run'],
        'view_mode': 'selected', 'view_enforced_by': 'server', 'source_fields_untrusted': True}


def service(tmp_path, handler=None, *, enabled=True, schema=None):
    seen = []
    def serve(req):
        seen.append(req)
        if req.url.path.endswith('/capabilities'):
            return success(capabilities(operations=list(OPERATIONS) if enabled else []))
        if req.url.path.endswith('/project-schema'):
            return success(CONTRACT if schema is None else schema)
        return handler(req) if handler else success(response())
    client = DraftClient('synthetic-test', transport=httpx.MockTransport(serve))
    return DraftService(Workspace(tmp_path), client), seen


def arguments(**updates):
    return dict(devices=devices(), links=links(), idempotency_key=KEY, **updates)


def test_prepare_exact_request_projection_and_integrity(tmp_path):
    def handle(req):
        assert req.method == 'POST' and req.url.path.endswith('/guided/projects')
        assert req.headers['Idempotency-Key'] == KEY
        assert json.loads(req.content) == {'devices': devices(), 'links': links()}
        data = response()
        data.update(source_config=CANARY, approval_ref=CANARY)
        data['cross_device_evidence']['checks'][0]['raw_line'] = CANARY
        return success(data)
    svc, seen = service(tmp_path, handle)
    result = svc.call('prepare_project', arguments())
    assert result['ok'], result
    Draft202012Validator(OUTPUT_SCHEMA).validate(result)
    assert CANARY not in json.dumps(result)
    assert len(seen) == 3


@pytest.mark.parametrize('bad', [
    {'devices': []}, {'devices': [{'device_id': 'a', 'draft_id': '../escape', 'revision': 1}]},
    {'links': [{'endpoints': []}]}, {'links': [{'endpoints': links()[0]['endpoints'], 'expectations': {'same_subnet': 'true'}}]},
    {'accepted_by': 'human'}, {'links': [{'endpoints': links()[0]['endpoints'], 'secret': CANARY}]},
    {'devices': [{**devices()[0], 'revision': True}]}, {'idempotency_key': ''},
])
def test_invalid_batch_never_mutates(tmp_path, bad):
    svc, seen = service(tmp_path)
    args = arguments()
    args.update(bad)
    result = svc.call('prepare_project', args)
    assert result['error']['code'] == 'invalid_arguments', result
    assert not any(req.method == 'POST' for req in seen)


def test_disabled_and_unknown_schema_never_mutate(tmp_path):
    for enabled, schema in [(False, None), (True, {**CONTRACT, 'version': 'project_99'})]:
        svc, seen = service(tmp_path, enabled=enabled, schema=schema)
        assert svc.call('prepare_project', arguments())['error']['code'] == 'unsupported_capability'
        assert not any(req.method == 'POST' for req in seen)


@pytest.mark.parametrize('mutation', ['project_id', 'revision', 'hash', 'evidence_hash', 'approval', 'runtime', 'index', 'reason', 'stale'])
def test_invalid_response_does_not_claim_success(tmp_path, mutation):
    data = response()
    if mutation == 'project_id': data['project_id'] = 'project_' + '2' * 32
    if mutation == 'revision': data['revision'] = 2
    if mutation == 'hash': data['snapshot']['devices'][0]['revision'] = 3
    if mutation == 'evidence_hash': data['cross_device_evidence']['project_content_sha256'] = 'f' * 64
    if mutation == 'approval': data['approval_available'] = True
    if mutation == 'runtime': data['validation']['target_runtime'] = 'pass'
    if mutation == 'index': data['cross_device_evidence']['checks'][0]['link_index'] = 1
    if mutation == 'reason': data['cross_device_evidence']['checks'][0]['reason'] = CANARY
    if mutation == 'stale': data['stale_devices'] = ['a']
    svc, _ = service(tmp_path, lambda req: success(data))
    result = svc.call('get_project', {'project_id': PROJECT, 'revision': 1})
    assert result['error']['code'] == 'invalid_response'
    assert CANARY not in json.dumps(result)


@pytest.mark.parametrize('code', ['revision_conflict', 'idempotency_conflict', 'revalidation_required', 'access_denied', 'not_found'])
def test_conflicts_not_retried_or_reclassified(tmp_path, code):
    svc, seen = service(tmp_path, lambda req: httpx.Response(409, json={'success': False,
        'error': {'code': code, 'message': CANARY}}))
    result = svc.call('propose_project', arguments(project_id=PROJECT, expected_revision=1))
    assert result['error']['code'] == code
    assert sum(req.method == 'POST' for req in seen) == 1
    assert CANARY not in json.dumps(result)


def test_read_stale_revision_and_retry_return_same_identity(tmp_path):
    data = response(2)
    data.update(state='stale', stale_devices=['a'], current_revision=3)
    def handle(req):
        if req.method == 'POST':
            assert json.loads(req.content)['expected_revision'] == 1
        else:
            assert req.url.params['revision'] == '2'
        return success(data)
    svc, seen = service(tmp_path, handle)
    first = svc.call('propose_project', arguments(project_id=PROJECT, expected_revision=1))
    assert first['ok'], first
    assert svc.call('propose_project', arguments(project_id=PROJECT, expected_revision=1)) == first
    assert svc.call('get_project', {'project_id': PROJECT, 'revision': 2}) == first


@pytest.mark.parametrize('method,path', [('POST', 'guided/project-schema'), ('GET', 'guided/projects'),
    ('POST', 'guided/projects/' + PROJECT), ('GET', 'guided/projects/' + PROJECT + '/proposals'),
    ('POST', 'guided/projects/' + PROJECT + '/approve'), ('POST', 'guided/projects/' + PROJECT + '/execute')])
def test_route_guard_has_no_project_approval_or_execution(method, path):
    with pytest.raises(ValueError):
        DraftClient._check_route(method, path)


def test_project_tools_discovery_and_direct_invocation_recheck(tmp_path):
    from netconverter_cli.mcp_server import Bridge
    svc, seen = service(tmp_path)
    bridge = Bridge(tmp_path, 'https://api.netconverter.ai/external/v1', guided=True, draft_service=svc)
    assert set(OPERATIONS) <= {t['name'] for t in bridge.list_tools()}
    result = bridge.call('prepare_project', arguments())
    assert result['structuredContent']['ok'], result
    assert result['structuredContent']['data']['project']['submission_readiness'] == 'blocked'
    svc2, seen2 = service(tmp_path, enabled=False)
    bridge._draft_service = svc2
    assert {t['name'] for t in bridge.list_tools()} == {'account'}
    result = bridge.call('prepare_project', arguments())
    assert result['structuredContent']['error']['code'] == 'unsupported_capability'
    assert all(r.method == 'GET' for r in seen2)


def test_project_cli_uses_same_contract_without_ai(tmp_path, monkeypatch, capsys):
    from netconverter_cli import cli, drafts
    from test_draft_cli import install_transport
    seen = []
    def handle(req):
        seen.append(req)
        if req.url.path.endswith('/capabilities'):
            return success(capabilities(operations=list(OPERATIONS)))
        if req.url.path.endswith('/project-schema'):
            return success(CONTRACT)
        return success(response())
    install_transport(monkeypatch, handle)
    cli.main(['--workspace', str(tmp_path), 'project', 'prepare', '--devices', json.dumps(devices()),
              '--links', json.dumps(links()), '--idempotency-key', KEY])
    result = json.loads(capsys.readouterr().out)
    assert result['ok'] and result['data']['project']['project_id'] == PROJECT
    assert len(seen) == 3
    cli.main(['--workspace', str(tmp_path), 'project', 'get', PROJECT, '--revision', '1'])
    assert json.loads(capsys.readouterr().out)['ok']
    with pytest.raises(SystemExit):
        cli.main(['--workspace', str(tmp_path), 'project', 'prepare', '--devices', CANARY,
                  '--links', '[]', '--idempotency-key', KEY])
    out = capsys.readouterr().out
    assert json.loads(out)['error']['code'] == 'invalid_arguments'
    assert CANARY not in out and len(seen) == 5
