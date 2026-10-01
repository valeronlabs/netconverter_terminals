import hashlib
from unittest.mock import Mock
import pytest
from textual.widgets import Input,OptionList,RichLog,Button
from netconverter_terminal.controller import Controller
from netconverter_terminal.tui import Terminal
from netconverter_terminal.providers import ProviderError


def client():
    c=Mock()
    c.capabilities.return_value={'remaining':{'convert':3,'analysis':20,'query':100},'targets':['palo_alto_set','palo_alto_xml','palo_alto_panorama'],'panos_versions':['11.2'],'routing_engines':['lr','vr'],'pipeline_modes':['like_for_like']}
    c.upload.side_effect=lambda content,vendor:{'configuration_id':'cfg_example','source_sha256':hashlib.sha256(content).hexdigest(),'vendor':vendor}
    c.submit.return_value={'job_id':'trm_example','status':'queued'}
    return c


async def choose(app,pilot,index=0):
    app.query_one(OptionList).highlighted=index
    await pilot.press('enter')
    await pilot.pause()


async def enter(app,pilot,value):
    app.query_one(Input).value=value
    await pilot.press('enter')
    await pilot.pause()


def history(app):
    return '\n'.join(line.text for line in app.query_one(RichLog).lines)


@pytest.mark.asyncio
@pytest.mark.parametrize('size',[(126,41),(80,24)])
async def test_keyboard_conversion_no_buttons_or_modals(tmp_path,size):
    (tmp_path/'source.cfg').write_text('synthetic config')
    api=client()
    controller=Controller(tmp_path,api)
    app=Terminal(controller)
    async with app.run_test(size=size) as pilot:
        await pilot.pause()
        await enter(app,pilot,'/convert')
        assert len(app.screen_stack)==1
        assert not app.query(Button)
        assert 'ASA source file' in str(app.query_one('#question').render())
        assert app.query_one(OptionList).region.bottom <= size[1]-2
        await choose(app,pilot) # source
        api.upload.assert_not_called()
        await choose(app,pilot) # upload confirmed as ASA
        api.upload.assert_called_once_with(b'synthetic config','cisco_asa')
        assert 'Palo Alto output' in str(app.query_one('#question').render())
        for _ in range(6): # SET, PANOS, router, mode, keep objects, presets
            await choose(app,pilot)
        api.submit.assert_not_called()
        assert 'Submit this conversion' in str(app.query_one('#question').render())
        await choose(app,pilot)
        api.submit.assert_called_once()
        assert api.submit.call_args.args[2]=={'target_vendor':'palo_alto_set','panos_target_version':'11.2','routing_engine':'lr','pipeline_mode':'like_for_like','remove_unused_objects':False}
        assert 'trm_example' in history(app)
        assert len(app.screen_stack)==1
        assert not app.query_one(Input).password


@pytest.mark.asyncio
async def test_panorama_advanced_choices_are_explicit(tmp_path):
    api=client();c=Controller(tmp_path,api)
    c.state['selected']='cfg_example';c.state['configurations']['cfg_example']={'vendor':'cisco_asa'}
    app=Terminal(c)
    async with app.run_test(size=(100,35)) as pilot:
        await pilot.pause()
        app.dispatch('/convert')
        await choose(app,pilot,2) # Panorama
        for _ in range(3): await choose(app,pilot)
        await enter(app,pilot,'')
        assert 'required' in history(app)
        api.submit.assert_not_called()
        await enter(app,pilot,'DEMO_GROUP')
        await enter(app,pilot,'DEMO_TEMPLATE')
        await choose(app,pilot,1) # cleanup
        await choose(app,pilot,1) # customize
        for _ in range(5): await choose(app,pilot,1)
        await enter(app,pilot,'DEMO_PROFILE')
        await enter(app,pilot,'bad JSON')
        api.submit.assert_not_called()
        await enter(app,pilot,'{"inside":"Trust"}')
        await choose(app,pilot)
        options=api.submit.call_args.args[2]
        assert options['panorama_device_group']=='DEMO_GROUP'
        assert options['panorama_template']=='DEMO_TEMPLATE'
        assert options['enable_appid'] is True
        assert options['app_id_implementation']=='dual_stack'
        assert options['implicit_deny']=='explicit-deny-all'
        assert options['remove_unused_objects'] is True
        assert options['zone_mapping']=={'inside':'Trust'}


@pytest.mark.asyncio
async def test_model_retry_preserves_old_and_secret_never_echoes(tmp_path,monkeypatch):
    from netconverter_terminal import setup
    old=Mock(name='old');old.name='ollama';old.model='local-model'
    new=Mock(name='new');new.name='openai';new.model='test-model'
    monkeypatch.setattr(setup,'connect_model',Mock(side_effect=[ProviderError('authentication'),new]))
    save=Mock(return_value=True);monkeypatch.setattr(setup,'save_model',save)
    c=Controller(tmp_path,client(),old);app=Terminal(c)
    async with app.run_test(size=(80,24)) as pilot:
        await pilot.pause()
        app.dispatch('/model')
        await choose(app,pilot)
        await enter(app,pilot,'test-model')
        assert app.query_one(Input).password
        await enter(app,pilot,'PRIVATE_PROVIDER_KEY')
        await pilot.pause(.2)
        assert '401' in history(app)
        assert c.provider is old
        save.assert_not_called()
        await choose(app,pilot) # retry
        await choose(app,pilot) # openai
        await enter(app,pilot,'test-model')
        await enter(app,pilot,'PRIVATE_PROVIDER_KEY')
        await pilot.pause(.2)
        assert c.provider is new
        old.close.assert_called_once()
        assert 'PRIVATE_PROVIDER_KEY' not in history(app)
        assert not app.query_one(Input).password
        assert app.query_one(Input).value==''


@pytest.mark.asyncio
async def test_escape_and_workspace_limits(tmp_path):
    (tmp_path/'large.cfg').write_bytes(b'x'*50001)
    (tmp_path/'escape.cfg').symlink_to('/etc/hosts')
    api=client();app=Terminal(Controller(tmp_path,api))
    async with app.run_test() as pilot:
        await pilot.pause()
        app.dispatch('/convert')
        assert all('escape' not in label for label,_ in app.choice_values)
        await choose(app,pilot) # oversize
        assert '50,000' in history(app)
        api.upload.assert_not_called()
        await pilot.press('escape')
        assert app.answer_callback is None
        api.submit.assert_not_called()
        app.dispatch('/model')
        await pilot.press('down')
        assert app.query_one(OptionList).highlighted==1
        await pilot.press('up')
        await choose(app,pilot)
        await enter(app,pilot,'test-model')
        app.query_one(Input).value='PRIVATE_KEY'
        await pilot.press('escape')
        assert app.query_one(Input).value==''
        assert not app.query_one(Input).password
        assert 'PRIVATE_KEY' not in history(app)


@pytest.mark.asyncio
async def test_palo_source_convert_requests_asa_instead_of_dead_end(tmp_path):
    c=Controller(tmp_path,client());c.state['selected']='cfg_palo'
    c.state['configurations']['cfg_palo']={'vendor':'palo_alto_xml'}
    app=Terminal(c)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.dispatch('/convert')
        assert 'Choose an ASA source file' in str(app.query_one('#question').render())
        assert 'Palo Alto files can be analyzed' in history(app)
        c.client.submit.assert_not_called()
