import json
import pytest
from unittest.mock import Mock
from netconverter_terminal import setup


@pytest.mark.parametrize('saved', [{}, {'server': 'http://127.0.0.1:18010/external/v1'}])
def test_plain_commands_use_selected_server_credential(tmp_path, monkeypatch, saved):
    from netconverter_terminal import cli
    monkeypatch.setattr(cli, 'load_settings', lambda _: saved)
    secret = Mock(return_value='PRODUCTION_KEY')
    monkeypatch.setattr(cli, 'get_secret', secret)
    client = Mock()
    client.jobs.return_value = {'jobs': []}
    factory = Mock(return_value=client)
    monkeypatch.setattr(cli, 'Client', factory)
    server = 'https://api.netconverter.ai/external/v1'
    cli.main(['--workspace', str(tmp_path), '--server', server, 'jobs'])
    secret.assert_called_once_with(setup.account(server))
    factory.assert_called_once_with('PRODUCTION_KEY', server)


def test_setup_validates_server_and_keeps_keys_out_of_workspace(tmp_path, monkeypatch):
    client = Mock()
    client.capabilities.return_value = {'profile':'terminal_quick', 'remaining':{'convert':3}}
    monkeypatch.setattr(setup, 'Client', Mock(return_value=client))
    save = Mock(return_value=True)
    monkeypatch.setattr(setup, 'save_secret', save)
    answers = iter(['https://pilot.example/external/v1', 'none'])
    c, p = setup.configure(tmp_path, ask=lambda _:next(answers), secret=lambda _:'UNIQUE_SERVER_SECRET')
    stored = (tmp_path/'.netconverter/connection.json').read_text()
    assert 'UNIQUE_SERVER_SECRET' not in stored
    assert json.loads(stored)['server'] == 'https://pilot.example/external/v1'
    assert p is None
    assert save.call_args.args == (setup.account('https://pilot.example/external/v1'), 'UNIQUE_SERVER_SECRET')
    assert setup.account('https://another.example/external/v1') != save.call_args.args[0]


def test_failed_model_stays_guided_without_fallback(tmp_path, monkeypatch):
    client = Mock()
    client.capabilities.return_value = {'profile':'terminal_quick'}
    monkeypatch.setattr(setup, 'Client', Mock(return_value=client))
    monkeypatch.setattr(setup, 'save_secret', Mock(return_value=False))
    provider = Mock()
    provider.select.side_effect = RuntimeError('PRIVATE_PROVIDER_PAYLOAD')
    factory = Mock(return_value=provider)
    monkeypatch.setattr(setup, 'Provider', factory)
    answers = iter(['https://pilot.example/external/v1','ollama','local-model','guided'])
    c, p = setup.configure(tmp_path, ask=lambda _:next(answers), secret=lambda _:'SECRET')
    assert p is None and factory.call_count == 1
    assert setup.load_settings(tmp_path)['provider'] is None


def test_failed_model_retry_preserves_server_and_saves_only_verified_model(tmp_path,monkeypatch,capsys):
    from netconverter_terminal.providers import ProviderError
    client=Mock()
    client.capabilities.return_value={'profile':'terminal_quick'}
    monkeypatch.setattr(setup,'Client',Mock(return_value=client))
    save=Mock(return_value=True)
    monkeypatch.setattr(setup,'save_secret',save)
    bad=Mock()
    bad.select.side_effect=ProviderError('authentication')
    good=Mock(name='provider')
    good.name='openai'
    good.model='test-model'
    good.key='SECOND_SECRET'
    good.select.return_value='unused_objects'
    monkeypatch.setattr(setup,'Provider',Mock(side_effect=[bad,good]))
    answers=iter(['','openai','test-model','retry','openai','test-model'])
    secrets=iter(['SERVER_SECRET','FIRST_SECRET','SECOND_SECRET'])
    c,p=setup.configure(tmp_path,ask=lambda _:next(answers),secret=lambda _:next(secrets))
    assert c is client and p is good
    bad.close.assert_called_once()
    assert setup.load_settings(tmp_path)['provider']=='openai'
    saved_text=(tmp_path/'.netconverter/connection.json').read_text()
    output=capsys.readouterr().out
    assert '401' in output
    for marker in ('SERVER_SECRET','FIRST_SECRET','SECOND_SECRET'):
        assert marker not in output and marker not in saved_text
    assert ('openai','FIRST_SECRET') not in [call.args for call in save.call_args_list]


def test_key_in_url_is_reprompted_not_requested(tmp_path,monkeypatch,capsys):
    client=Mock()
    client.capabilities.return_value={'profile':'terminal_quick'}
    factory=Mock(return_value=client)
    monkeypatch.setattr(setup,'Client',factory)
    monkeypatch.setattr(setup,'save_secret',Mock(return_value=True))
    answers=iter(['nck_live_SYNTHETIC_SECRET','','none'])
    setup.configure(tmp_path,ask=lambda _:next(answers),secret=lambda _:'SERVER_KEY')
    assert 'SYNTHETIC_SECRET' not in capsys.readouterr().out
    assert all('SYNTHETIC_SECRET' not in str(call) for call in factory.call_args_list)
