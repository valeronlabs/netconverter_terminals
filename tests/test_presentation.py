import json
from unittest.mock import Mock
import pytest
from rich.console import Console
from textual.widgets import Input, RichLog, Static, Button, Select
from netconverter_terminal.controller import Controller
from netconverter_terminal.tui import Terminal
from netconverter_terminal.providers import ProviderError
from netconverter_terminal.presentation import details_view


def api():
    client=Mock()
    client.capabilities.return_value={'remaining':{'convert':2,'analysis':20,'query':100}}
    return client


def log_text(app):
    return '\n'.join(line.text for line in app.query_one(RichLog).lines)


@pytest.mark.asyncio
@pytest.mark.parametrize('size',[(126,41),(80,24)])
async def test_help_and_prompt_fit_without_json(tmp_path,size):
    app=Terminal(Controller(tmp_path,api()))
    async with app.run_test(size=size) as pilot:
        await pilot.pause()
        app.dispatch('/help')
        await pilot.pause()
        text=log_text(app)
        assert 'Commands' in text and '/model' in text
        assert '\\n' not in text and '"help":' not in text
        field=app.query_one('#prompt',Input)
        assert field.region.bottom <= size[1]-1
        assert field.region.width <= size[0]
        app.dispatch('find unused objects')
        await pilot.pause()
        assert 'Connect a model with /model' in log_text(app)
        app.dispatch('/clear')
        await pilot.pause()
        assert 'Connect a model with /model' not in log_text(app)


def test_report_markup_is_literal_and_lists_are_readable():
    console=Console(record=True,width=80)
    console.print(details_view({'unused_objects':['[link=https://evil.invalid]NAME[/link]'], 'total':1}))
    rendered=console.export_text()
    assert '[link=https://evil.invalid]NAME[/link]' in rendered
    assert 'unused objects' in rendered
    assert '{' not in rendered


@pytest.mark.asyncio
async def test_download_failure_retry_preserves_server_verdict(tmp_path):
    from netconverter_terminal.workspace import WorkspaceError
    client=api()
    controller=Controller(tmp_path,client)
    controller.state['active_job']='trm_example'
    controller.download=Mock(side_effect=[WorkspaceError('Artifact checksum failed; no file was written'),{'job_id':'trm_example','saved':[]}])
    app=Terminal(controller)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.show_result({'job_id':'trm_example','status':'completed','translation_status':'passed_with_warnings','progress':100})
        await pilot.pause(0.3)
        assert 'trm_example' not in app.downloaded_jobs
        assert 'passed with warnings' in log_text(app)
        assert 'checksum failed' in log_text(app)
        app.dispatch('/download')
        await pilot.pause(0.3)
        assert 'trm_example' in app.downloaded_jobs
        assert controller.download.call_count==2


def test_long_workspace_path_stays_on_one_header_line():
    from netconverter_terminal.branding import banner
    console=Console(record=True,width=76)
    console.print(banner('/demo/'+'long-folder/'*20,compact=True,width=80))
    lines=console.export_text().splitlines()
    assert len(lines)==3
    assert lines[-1].endswith('…')

@pytest.mark.asyncio
async def test_unlimited_allowance_is_readable(tmp_path):
    client=api()
    client.capabilities.return_value={'remaining':{'convert':None,'analysis':20,'query':100}}
    app=Terminal(Controller(tmp_path,client))
    async with app.run_test() as pilot:
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert 'Unlimited conversions' in str(app.query_one('#context',Static).render())
        app.show_result(client.capabilities.return_value)
        await pilot.pause()
        assert 'Unlimited' in log_text(app)
        assert 'None' not in log_text(app)
