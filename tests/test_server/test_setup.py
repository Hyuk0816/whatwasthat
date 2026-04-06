import json


def test_gemini_hook_script_created(tmp_path):
    from whatwasthat.cli.app import _install_gemini_hook
    hooks_dir = tmp_path / "hooks"
    hooks_dir.mkdir()
    _install_gemini_hook(hooks_dir)
    script = hooks_dir / "gemini_ingest.sh"
    assert script.exists()
    content = script.read_text()
    assert "wwt ingest" in content
    assert '{"decision": "allow"}' in content


def test_gemini_settings_registered(tmp_path):
    from whatwasthat.cli.app import _register_gemini_hook
    settings_path = tmp_path / "settings.json"
    _register_gemini_hook(settings_path)
    settings = json.loads(settings_path.read_text())
    assert "AfterAgent" in settings["hooks"]


def test_gemini_settings_idempotent(tmp_path):
    from whatwasthat.cli.app import _register_gemini_hook
    settings_path = tmp_path / "settings.json"
    assert _register_gemini_hook(settings_path) is True
    assert _register_gemini_hook(settings_path) is False
