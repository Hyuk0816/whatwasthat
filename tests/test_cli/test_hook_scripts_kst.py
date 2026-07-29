"""Hook 스크립트 KST 고정 회귀 테스트 (Task 6)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock


def _assert_kst_script(content: str) -> None:
    assert "TZ=Asia/Seoul date +%Y-%m-%dT%H:%M:%S%z" in content
    assert "reason=missing_or_invalid_transcript" in content
    assert ' enqueue "$TRANSCRIPT_PATH" --source ' in content
    assert ' ingest "$TRANSCRIPT_PATH"' not in content


def test_install_gemini_hook_uses_kst_timestamp(tmp_path):
    from whatwasthat.cli.app import _install_gemini_hook

    hooks_dir = tmp_path / "hooks"
    hooks_dir.mkdir()

    script = _install_gemini_hook(hooks_dir)

    _assert_kst_script(script.read_text())


def test_install_codex_hook_uses_kst_timestamp(tmp_path):
    from whatwasthat.cli.app import _install_codex_hook

    hooks_dir = tmp_path / "hooks"
    hooks_dir.mkdir()

    script = _install_codex_hook(hooks_dir)

    _assert_kst_script(script.read_text())


def test_setup_creates_claude_hook_with_kst_timestamp(tmp_data_dir, monkeypatch):
    import whatwasthat.cli.app as app_module

    fake_home = tmp_data_dir / "home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: fake_home)

    class _FakeVectorStore:
        def __init__(self, db_path, model_name=None):
            self.db_path = db_path
            self.model_name = model_name

        def initialize(self):
            return None

    class _FakeCfg:
        chroma_path = tmp_data_dir / "vector"
        home_dir = fake_home / ".wwt"
        data_dir = fake_home / ".wwt" / "data"

        def __init__(self):
            self.home_dir.mkdir(parents=True, exist_ok=True)
            self.data_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(app_module, "_get_config", lambda: _FakeCfg())
    monkeypatch.setattr(app_module, "_bulk_ingest_directory", lambda *a, **k: None)
    monkeypatch.setattr("whatwasthat.storage.vector.VectorStore", _FakeVectorStore)
    monkeypatch.setattr("shutil.which", lambda name: None)
    monkeypatch.setattr(app_module, "_install_gemini_hook", lambda *a, **k: Path("/tmp/noop"))
    monkeypatch.setattr(app_module, "_register_gemini_hook", lambda *a, **k: False)
    monkeypatch.setattr(app_module, "_install_codex_hook", lambda *a, **k: Path("/tmp/noop"))

    fake_result = MagicMock()
    fake_result.returncode = 0
    fake_result.stdout = ""
    monkeypatch.setattr("subprocess.run", lambda *a, **k: fake_result)

    app_module.setup()

    script = fake_home / ".claude" / "hooks" / "wwt_auto_ingest.sh"
    assert script.exists()
    _assert_kst_script(script.read_text())
