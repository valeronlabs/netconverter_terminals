import base64
import hashlib
import pytest
from netconverter_terminal.controller import Controller
from netconverter_terminal.api import APIError
from netconverter_terminal.workspace import WorkspaceError
from netconverter_terminal.tui import Terminal


class FakeClient:
    def __init__(self):
        self.keys = []
        self.fail = True

    def upload(self, content, vendor):
        return {
            "configuration_id": "cfg_" + "a" * 32,
            "source_sha256": hashlib.sha256(content).hexdigest(),
            "vendor": vendor,
        }

    def submit(self, config, op, options, key):
        self.keys.append(key)
        if self.fail:
            self.fail = False
            raise APIError(0, "connection_failed")
        return {"job_id": "psc_" + "b" * 12, "status": "queued"}

    def status(self, job):
        return {"job_id": job, "status": "completed", "progress": 100}

    def artifacts(self, job):
        return {
            "artifacts": [
                {
                    "artifact_id": "report",
                    "filename": "report.txt",
                    "sha256": hashlib.sha256(b"report").hexdigest(),
                    "bytes": 6,
                }
            ]
        }

    def download(self, job, artifact):
        return {
            **self.artifacts(job)["artifacts"][0],
            "content_base64": base64.b64encode(b"report").decode(),
        }

    def capabilities(self):
        return {"remaining": {"convert": 3}}


def test_interrupted_submission_resume_and_preserve(tmp_path):
    (tmp_path / "input").mkdir()
    (tmp_path / "input" / "asa.cfg").write_text("synthetic config")
    api = FakeClient()
    c = Controller(tmp_path, api)
    c.select("input/asa.cfg", "cisco_asa")
    with pytest.raises(APIError):
        c.submit("analyze")
    restarted = Controller(tmp_path, api)
    assert restarted.resume()["status"] == "queued"
    assert api.keys[0] == api.keys[1]
    paths = restarted.download()["saved"]
    assert str(tmp_path / "input") in paths[0]
    assert (tmp_path / "input" / "asa.cfg").read_text() == "synthetic config"
    assert (
        "synthetic config" not in (tmp_path / ".netconverter/session.json").read_text()
    )
    assert restarted.download()["saved"] == paths
    from pathlib import Path

    Path(paths[0]).write_text("my edits")
    with pytest.raises(WorkspaceError):
        restarted.download()


@pytest.mark.asyncio
async def test_textual_guided_interaction(tmp_path):
    c = Controller(tmp_path, FakeClient())
    app = Terminal(c)
    async with app.run_test() as pilot:
        from textual.widgets import Input, Static

        field = app.query_one(Input)
        field.value = "/allowance"
        await pilot.press("enter")
        await pilot.pause()
        assert c.allowance["remaining"]["convert"] == 3
        assert "3 conversions" in str(app.query_one("#context", Static).render())
        assert app.controller.provider is None


@pytest.mark.asyncio
async def test_conversion_form_requires_choices(tmp_path):
    from netconverter_terminal.forms import ConversionForm
    from textual.widgets import Static, Select

    c = Controller(tmp_path, FakeClient())
    app = Terminal(c)
    caps = {
        "targets": ["palo_alto_set", "palo_alto_panorama"],
        "panos_versions": ["11.2"],
        "routing_engines": ["vr", "lr"],
        "pipeline_modes": ["like_for_like"],
    }
    async with app.run_test(size=(100, 45)) as pilot:
        form = ConversionForm(caps)
        app.push_screen(form)
        await pilot.pause()
        form.query_one("#submit").focus()
        await pilot.press("enter")
        await pilot.pause()
        assert "Choose each" in str(form.query_one("#error", Static).render())
        for field, value in [
            ("target_vendor", "palo_alto_panorama"),
            ("panos_target_version", "11.2"),
            ("routing_engine", "lr"),
            ("pipeline_mode", "like_for_like"),
        ]:
            form.query_one("#" + field, Select).value = value
        await pilot.pause()
        assert all(
            form.query_one("#" + field, Select).value is not Select.NULL
            for field in (
                "target_vendor",
                "panos_target_version",
                "routing_engine",
                "pipeline_mode",
            )
        )
        await pilot.pause(0.4)
        form.query_one("#submit").focus()
        await pilot.press("enter")
        await pilot.pause()
        assert "Panorama requires" in str(form.query_one("#error", Static).render())


def test_changing_revision_cannot_query_previous_job(tmp_path):
    (tmp_path / 'asa.cfg').write_text('synthetic config')
    api = FakeClient()
    c = Controller(tmp_path, api)
    c.state['active_job'] = 'psc_' + 'c' * 12
    c.select('asa.cfg', 'cisco_asa')
    with pytest.raises(WorkspaceError, match='completed job'):
        c.query('unused_objects')
    api.status = lambda job: {'job_id': job, 'status': 'completed', 'configuration_id': 'cfg_' + 'b' * 32}
    c.resume('psc_' + 'c' * 12)
    assert c.state['selected'] == 'cfg_' + 'b' * 32
    api.target = lambda job: {'configuration_id': 'cfg_' + 'd' * 32, 'vendor': 'palo_alto_set', 'source_sha256': 'a' * 64}
    c.target()
    with pytest.raises(WorkspaceError, match='completed job'):
        c.query('flow')
    restarted = Controller(tmp_path, api)
    assert restarted.state['selected'] == 'cfg_' + 'd' * 32
    assert 'active_job' not in restarted.state


def test_query_jsonb_reordering_keeps_replay_artifacts_stable(tmp_path):
    api = FakeClient()
    c = Controller(tmp_path, api)
    c.state['active_job'] = 'psc_' + 'b' * 12
    first = {'query_id': 'qry_' + 'c' * 32, 'details': {'total': 1, 'unused_networks': ['OBJECT']}, 'pagination': {}}
    replay = {'pagination': {}, 'details': {'unused_networks': ['OBJECT'], 'total': 1}, 'query_id': 'qry_' + 'c' * 32}
    api.query = lambda *a, **k: first.copy()
    paths = c.query('unused_objects')['saved']
    api.query = lambda *a, **k: replay.copy()
    assert c.query('unused_objects')['saved'] == paths


@pytest.mark.asyncio
async def test_open_convert_and_complete_download(tmp_path):
    from textual.widgets import Button, Input, Select, Checkbox
    from netconverter_terminal.forms import OpenForm, ConversionForm
    (tmp_path/'fresh.cfg').write_text('synthetic config')
    api = FakeClient()
    captured = []
    def submit(config, operation, options, key):
        captured.append(options)
        return {'job_id':'trm_'+'d'*12, 'status':'queued'}
    api.submit = submit
    api.capabilities = lambda: {'remaining':{'convert':3}, 'targets':['palo_alto_set'], 'panos_versions':['11.2'], 'routing_engines':['lr'], 'pipeline_modes':['like_for_like']}
    app = Terminal(Controller(tmp_path, api))
    async with app.run_test(size=(100,55)) as pilot:
        await pilot.pause()
        await pilot.click('#open_config')
        await pilot.pause()
        app.screen.query_one('#path',Input).value = 'fresh.cfg'
        app.screen.query_one('#open',Button).press()
        await pilot.pause()
        await pilot.click('#nav_convert')
        await pilot.pause()
        form = app.screen
        for key,value in [('target_vendor','palo_alto_set'),('panos_target_version','11.2'),('routing_engine','lr'),('pipeline_mode','like_for_like'),('appid','on'),('app_id_implementation','dual_stack'),('log_all_rules','on'),('add_security_profiles','on'),('implicit_deny','on')]:
            form.query_one('#'+key,Select).value = value
        form.query_one('#cleanup',Checkbox).value = True
        form.query_one('#default_profile_group',Input).value = 'PILOT_PROFILE'
        form.query_one('#submit',Button).press()
        await pilot.pause()
        assert captured[0]['default_profile_group'] == 'PILOT_PROFILE'
        assert captured[0]['implicit_deny'] == 'explicit-deny-all'
        app.action_refresh()
        await pilot.pause(0.3)
        assert list(tmp_path.glob('trm_*report.txt'))
        assert (tmp_path/'fresh.cfg').read_text() == 'synthetic config'
