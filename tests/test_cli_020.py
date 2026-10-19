"""NetConverter CLI 0.2.0: server-driven vendor menus, full-API jobs, the redesigned app."""
import io
import json

import httpx
import pytest
from rich.console import Console
from textual.widgets import Input, OptionList, RichLog

from netconverter_cli.api import ExternalClient, StaticCredential
from netconverter_cli.catalog import Catalog
from netconverter_cli.controller import Controller
from netconverter_cli.guided import guess_vendor
from netconverter_cli.presentation import details_view
from netconverter_cli.tui import Terminal

SERVER = 'https://api.netconverter.ai/external/v1'
CAPS = {
    'job_types': ['convert', 'validate', 'optimize'],
    'vendors': [
        {'code': 'cisco_asa', 'name': 'Cisco ASA', 'device_type': 'firewall', 'roles': ['source'], 'input': 'text'},
        {'code': 'check_point', 'name': 'Check Point', 'device_type': 'firewall', 'roles': ['source'], 'input': 'handoff_bundle'},
        {'code': 'fortinet', 'name': 'Fortinet FortiGate', 'device_type': 'firewall', 'roles': ['source', 'target'], 'input': 'text'},
        {'code': 'palo_alto_xml', 'name': 'Palo Alto (XML)', 'device_type': 'firewall', 'roles': ['source', 'target'], 'input': 'text'},
        {'code': 'cisco_ios_xe_router', 'name': 'Cisco IOS-XE', 'device_type': 'router', 'roles': ['source', 'target'], 'input': 'text'},
        {'code': 'juniper_junos_router', 'name': 'Juniper JunOS (Braces)', 'device_type': 'router', 'roles': ['source', 'target'], 'input': 'text'},
        {'code': 'cisco_ios_xe_switch', 'name': 'Cisco IOS-XE', 'device_type': 'switch', 'roles': ['source', 'target'], 'input': 'text'},
    ],
    'paths': [{'source': s, 'target': t, 'device_type': d} for s, t, d in [
        ('cisco_asa', 'fortinet', 'firewall'), ('cisco_asa', 'palo_alto_xml', 'firewall'),
        ('fortinet', 'palo_alto_xml', 'firewall'), ('palo_alto_xml', 'fortinet', 'firewall'),
        ('cisco_ios_xe_router', 'juniper_junos_router', 'router'),
        ('juniper_junos_router', 'cisco_ios_xe_router', 'router')]],
    'limits': {'max_config_bytes': 5 * 1024 * 1024, 'max_inflight_jobs': 25},
    'trial': False,
}
FORTI = 'config system global\n    set hostname "SYNTHETIC-FW"\nend\nconfig firewall address\nend\n'


class FullAPI:
    def __init__(self):
        self.requests = []

    def __call__(self, request):
        self.requests.append(request)
        path = request.url.path.removeprefix('/external/v1/')
        env = lambda data: httpx.Response(200, json={'success': True, 'data': data})
        if path == 'me':
            return env({'tenant_id': 't', 'job_types': CAPS['job_types']})
        if path == 'capabilities':
            return env(CAPS)
        if path == 'jobs' and request.method == 'POST':
            return env({'job_id': 'tra_0123456789ab', 'status': 'queued'})
        if path == 'jobs':
            return env({'jobs': [{'job_id': 'tra_0123456789ab', 'source_vendor': 'fortinet',
                                  'target_vendor': 'palo_alto_xml', 'status': 'completed',
                                  'translation_status': 'passed', 'job_type': 'convert'}]})
        if path.startswith('jobs/'):
            return env({'job_id': path.split('/')[1], 'status': 'queued', 'source_vendor': 'fortinet'})
        return httpx.Response(404, json={})


def external(tmp_path):
    server = FullAPI()
    client = ExternalClient(StaticCredential('nck_synthetic'), SERVER, transport=httpx.MockTransport(server))
    return Controller(tmp_path, client), server


def posts(server):
    return [json.loads(r.content) for r in server.requests if r.method == 'POST']


async def settle(app, pilot):
    await app.workers.wait_for_complete()
    await pilot.pause()


async def choose(app, pilot, index=0):
    app.query_one(OptionList).highlighted = index
    await pilot.press('enter')
    await settle(app, pilot)


def history(app):
    return '\n'.join(line.text for line in app.query_one(RichLog).lines)


def test_catalog_menus_follow_the_server():
    catalog = Catalog.from_external(CAPS)
    assert 'check_point' not in catalog.sources('convert')  # bundle-only, not a text upload
    assert catalog.targets('fortinet') == ['palo_alto_xml']
    labels = [text for text, _ in catalog.grouped(catalog.sources('validate'))]
    assert labels.index('Cisco IOS-XE · router') < labels.index('Cisco IOS-XE · switch')
    assert catalog.supports('validate') and catalog.max_bytes == 5 * 1024 * 1024
    quick = Catalog.from_quick({'targets': ['palo_alto_set'], 'remaining': {'convert': 2}})
    assert quick.sources('convert') == ['cisco_asa'] and quick.describe().startswith('Pilot key')


@pytest.mark.asyncio
async def test_fortigate_to_palo_alto_goes_through_full_api(tmp_path):
    (tmp_path / 'edge-fw.conf').write_text(FORTI)
    controller, server = external(tmp_path)
    app = Terminal(controller)
    async with app.run_test(size=(100, 32)) as pilot:
        await settle(app, pilot)
        app.dispatch('/convert')
        await pilot.pause()
        assert app.question == 'Convert which file?'
        await choose(app, pilot)  # edge-fw.conf
        assert app.question == 'What does edge-fw.conf contain?'
        detected = app.query_one(OptionList).highlighted
        assert app.choice_values[detected][1] == 'fortinet'
        assert 'detected' in app.choice_values[detected][0]
        assert not posts(server)  # nothing leaves before the review's Submit
        await choose(app, pilot, detected)
        assert app.question == 'Convert Fortinet FortiGate to'
        await choose(app, pilot)  # Palo Alto (XML)
        assert 'Palo Alto (XML)' in history(app)
        assert app.question == 'Submit this job?'
        await choose(app, pilot)
        body = posts(server)[0]
        assert body == {'source_vendor': 'fortinet', 'target_vendor': 'palo_alto_xml',
                        'technology': 'firewall', 'source_config': FORTI}
        assert 'tra_0123456789ab' in history(app)


@pytest.mark.asyncio
async def test_validate_and_jobs_on_full_api(tmp_path):
    (tmp_path / 'core.cfg').write_text('Building configuration...\nversion 17.3\ninterface GigabitEthernet1\n')
    controller, server = external(tmp_path)
    app = Terminal(controller)
    async with app.run_test(size=(126, 41)) as pilot:
        await settle(app, pilot)
        app.dispatch('/validate')
        await pilot.pause()
        await choose(app, pilot)
        assert app.choice_values[app.query_one(OptionList).highlighted][1] == 'cisco_ios_xe_router'
        await choose(app, pilot, app.query_one(OptionList).highlighted)
        await choose(app, pilot)  # Submit
        body = posts(server)[0]
        assert body['job_type'] == 'validate' and body['technology'] == 'router' and 'target_vendor' not in body
        app.dispatch('/jobs')
        await settle(app, pilot)
        assert 'Fortinet FortiGate → Palo Alto (XML)' in history(app) and 'PASSED' in history(app)


@pytest.mark.asyncio
async def test_choice_marker_digits_and_contextual_footer(tmp_path):
    controller, _ = external(tmp_path)
    app = Terminal(controller)
    async with app.run_test(size=(80, 24)) as pilot:
        await settle(app, pilot)
        assert app.check_action('cancel_input', ()) is False  # no question: Cancel hidden
        picked = []
        app.ask_choice('Pick one', [('First', 1), ('Second', 2), ('Third', 3)], picked.append)
        await pilot.pause()
        assert app.check_action('cancel_input', ()) is True
        options = app.query_one(OptionList)
        assert str(options.get_option_at_index(0).prompt).startswith('▸')
        await pilot.press('down')
        assert str(options.get_option_at_index(1).prompt).startswith('▸')
        assert not str(options.get_option_at_index(0).prompt).startswith('▸')
        await pilot.press('3')
        assert picked == [3] and app.answer_callback is None
        assert app.query_one('#prompt', Input).display


def test_review_labels_do_not_wrap_at_80_columns():
    console = Console(record=True, width=76, file=io.StringIO())
    console.print(details_view({'target_vendor': 'Palo Alto (XML)', 'pipeline_mode': 'like_for_like',
                                'remove_unused_objects': False, 'routing_engine': 'lr'}))
    lines = console.export_text().splitlines()
    assert any('Target' in l and 'Palo Alto (XML)' in l for l in lines)
    assert any('Mode' in l and 'Like for like' in l for l in lines)
    assert any('Routing' in l and 'Logical router (lr)' in l for l in lines)
    assert len(lines) == 4


@pytest.mark.asyncio
async def test_pilot_key_is_labelled_and_header_fits(tmp_path):
    from unittest.mock import Mock
    api = Mock()
    api.capabilities.return_value = {'remaining': {'convert': 3}, 'targets': ['palo_alto_set']}
    app = Terminal(Controller(tmp_path, api))
    async with app.run_test(size=(80, 24)) as pilot:
        await settle(app, pilot)
        app.dispatch('/allowance')
        await settle(app, pilot)
        assert 'Pilot key · ASA → Palo Alto only' in history(app)


@pytest.mark.parametrize('text,expected', [
    ('ASA Version 9.16\nhostname fw\n', 'cisco_asa'),
    (FORTI, 'fortinet'),
    ('<config version="11.1.0"><devices/></config>', 'palo_alto_xml'),
    ('set system host-name r1\nset interfaces ge-0/0/0 unit 0\n', 'juniper_set_router'),
    ('plain notes', None),
])
def test_vendor_guess_only_suggests_offered_codes(text, expected):
    offered = ['cisco_asa', 'fortinet', 'palo_alto_xml', 'juniper_set_router', 'juniper_set_switch']
    assert guess_vendor(text, offered) == expected
    assert guess_vendor(text, ['check_point']) is None


def test_connect_plans_show_then_write_with_backup(tmp_path, monkeypatch):
    from pathlib import Path
    from netconverter_cli import connect
    monkeypatch.setattr(Path, 'home', lambda: tmp_path)
    monkeypatch.setattr(connect, 'executable', lambda: '/opt/bin/netconverter')
    work = tmp_path / 'migrations'
    work.mkdir()
    (tmp_path / '.cursor').mkdir()
    (tmp_path / '.cursor' / 'mcp.json').write_text('{"mcpServers": {"other": {"command": "x"}}}')
    change = connect.plan('cursor', work)
    assert '"netconverter"' in change.preview and not connect._cursor_configured()
    change.apply()
    data = json.loads((tmp_path / '.cursor' / 'mcp.json').read_text())
    assert data['mcpServers']['other'] == {'command': 'x'}
    assert data['mcpServers']['netconverter']['args'] == ['mcp', '--workspace', str(work.resolve())]
    assert (tmp_path / '.cursor' / 'mcp.json.bak').exists() and connect._cursor_configured()
    codex = connect.plan('codex', work)
    codex.apply()
    assert connect._codex_configured()
    assert connect.plan('codex', work).can_apply is False  # never edits an existing table
    vscode = connect.plan('vscode', work)
    vscode.apply()
    assert 'VS Code' in connect.configured_clients(work)
    (tmp_path / '.cursor' / 'mcp.json').write_text('not json')
    assert connect.plan('cursor', work).can_apply is False
