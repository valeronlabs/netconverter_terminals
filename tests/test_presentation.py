import json
from unittest.mock import Mock
import pytest
from rich.console import Console
from textual.widgets import Input, RichLog, Static, Button, Select
from netconverter_terminal.controller import Controller
from netconverter_terminal.tui import Terminal
from netconverter_terminal.forms import ModelForm
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


@pytest.mark.asyncio
async def test_model_failure_can_be_corrected_without_restarting(tmp_path,monkeypatch):
    from netconverter_terminal import setup
    old=Mock()
    old.name='ollama'
    old.model='local-model'
    candidate=Mock()
    candidate.name='openai'
    candidate.model='test-model'
    candidate.key='PRIVATE_KEY'
    connect=Mock(side_effect=[ProviderError('authentication'),candidate])
    monkeypatch.setattr(setup,'connect_model',connect)
    save=Mock(return_value=True)
    monkeypatch.setattr(setup,'save_model',save)
    controller=Controller(tmp_path,api(),old)
    app=Terminal(controller)
    async with app.run_test(size=(100,40)) as pilot:
        await pilot.pause()
        app.dispatch('/model')
        await pilot.pause()
        form=app.screen
        form.query_one('#model_provider',Select).value='openai'
        form.query_one('#model_id',Input).value='test-model'
        form.query_one('#model_key',Input).value='PRIVATE_KEY'
        assert form.query_one('#model_key',Input).password
        form.query_one('#connect_model',Button).press()
        await pilot.pause(0.3)
        assert app.screen is form
        assert '401' in str(form.query_one('#error',Static).render())
        assert form.query_one('#model_key',Input).value==''
        assert controller.provider is old
        save.assert_not_called()
        form.query_one('#model_key',Input).value='PRIVATE_KEY'
        form.query_one('#connect_model',Button).press()
        await pilot.pause(0.3)
        assert controller.provider is candidate
        old.close.assert_called_once()
        assert 'Model connected: openai / test-model' in log_text(app)
        assert 'PRIVATE_KEY' not in log_text(app)


def test_report_markup_is_literal_and_lists_are_readable():
    console=Console(record=True,width=80)
    console.print(details_view({'unused_objects':['[link=https://evil.invalid]NAME[/link]'], 'total':1}))
    rendered=console.export_text()
    assert '[link=https://evil.invalid]NAME[/link]' in rendered
    assert 'unused objects' in rendered
    assert '{' not in rendered


@pytest.mark.asyncio
@pytest.mark.parametrize('size',[(126,41),(80,24)])
async def test_finished_welcome_has_accessible_actions(tmp_path,size):
    app=Terminal(Controller(tmp_path,api()))
    async with app.run_test(size=size) as pilot:
        await pilot.pause()
        assert app.query_one('#welcome').display
        assert not app.query_one('#conversation').display
        # The command list and persistent prompt fit without scrolling at both sizes.
        assert app.query_one('#help').region.bottom <= app.query_one('#activity').region.y
        assert app.query_one('#open_config').region.y > app.query_one('#context').region.y
        await pilot.click('#model')
        await pilot.pause()
        assert isinstance(app.screen,ModelForm)


@pytest.mark.asyncio
async def test_file_browser_quick_convert_requires_asa_and_limit(tmp_path):
    from netconverter_terminal.forms import OpenForm,ConversionForm
    (tmp_path/'source.asa').write_text('synthetic')
    (tmp_path/'large.cfg').write_bytes(b'x'*50001)
    (tmp_path/'escape.cfg').symlink_to('/etc/hosts')
    client=api()
    import hashlib
    client.upload.return_value={'configuration_id':'cfg_example','source_sha256':hashlib.sha256(b'synthetic').hexdigest()}
    client.capabilities.return_value.update(targets=['palo_alto_set'],panos_versions=['11.2'],routing_engines=['lr'],pipeline_modes=['like_for_like'])
    app=Terminal(Controller(tmp_path,client))
    async with app.run_test(size=(100,40)) as pilot:
        await pilot.pause()
        app.dispatch('/open')
        await pilot.pause()
        form=app.screen
        assert isinstance(form,OpenForm)
        assert not any(p.name=='escape.cfg' for p in form.entries.values())
        client.upload.assert_not_called()
        form.query_one('#path',Input).value='source.asa'
        form.query_one('#vendor',Select).value='palo_alto_set'
        form.query_one('#quick_convert',Button).press()
        await pilot.pause()
        assert 'Cisco ASA' in str(form.query_one('#error',Static).render())
        client.upload.assert_not_called()
        form.query_one('#vendor',Select).value='cisco_asa'
        form.query_one('#path',Input).value='large.cfg'
        form.query_one('#quick_convert',Button).press()
        await pilot.pause()
        assert '50,000' in str(form.query_one('#error',Static).render())
        client.upload.assert_not_called()
        form.query_one('#path',Input).value='source.asa'
        form.query_one('#quick_convert',Button).press()
        await pilot.pause(0.3)
        client.upload.assert_called_once_with(b'synthetic','cisco_asa')
        assert isinstance(app.screen,ConversionForm)
        client.submit.assert_not_called()


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
