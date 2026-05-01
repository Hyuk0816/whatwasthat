"""wwt remote-ingest / remote-ingest-all CLI 동작 검증."""

from __future__ import annotations

import importlib
from types import SimpleNamespace

from typer.testing import CliRunner


def test_wwt_home_respects_env_override(tmp_data_dir, monkeypatch):
    """WWT_HOME 환경변수가 있으면 WwtConfig가 해당 경로를 사용해야 한다."""
    custom_home = tmp_data_dir / "custom-home"
    monkeypatch.setenv("WWT_HOME", str(custom_home))

    import whatwasthat.config as config_module

    config_module = importlib.reload(config_module)
    cfg = config_module.WwtConfig()

    assert cfg.home_dir == custom_home
    assert cfg.data_dir == custom_home / "data"


def test_remote_ingest_uses_current_project_for_date_scope(tmp_data_dir, monkeypatch):
    """remote-ingest는 기본적으로 cwd 프로젝트 + 날짜 범위만 업로드해야 한다."""
    import whatwasthat.cli.app as app_module

    project_dir = tmp_data_dir / "myproj"
    project_dir.mkdir()
    monkeypatch.chdir(project_dir)

    captured: dict = {}

    def _fake_collect(*, env, date, source=None, project=None):
        captured["collect"] = {
            "env": env,
            "date": date,
            "source": source,
            "project": project,
        }
        return [
            SimpleNamespace(
                env=env,
                source="claude-code",
                project="myproj",
                project_path=str(project_dir),
                git_branch="main",
                original_session_id="s1",
                filename="session.jsonl",
                started_at="2026-05-01T00:00:00+09:00",
                transcript_text="hello",
            )
        ]

    class _FakeClient:
        def __init__(self, config):
            self.config = config

        def upload_sessions(self, sessions):
            captured["uploaded"] = list(sessions)
            return {"uploaded": len(captured["uploaded"]), "failed": 0, "skipped": 0}

    monkeypatch.setattr(
        "whatwasthat.remote.discovery.collect_sessions_for_date",
        _fake_collect,
    )
    monkeypatch.setattr("whatwasthat.remote.client.RemoteGatewayClient", _FakeClient)

    runner = CliRunner()
    result = runner.invoke(
        app_module.app,
        ["remote-ingest", "--env", "home", "--date", "2026-05-01"],
    )

    assert result.exit_code == 0, result.output
    assert captured["collect"] == {
        "env": "home",
        "date": "2026-05-01",
        "source": None,
        "project": "myproj",
    }
    assert len(captured["uploaded"]) == 1


def test_remote_ingest_allows_all_projects(tmp_data_dir, monkeypatch):
    """remote-ingest --all-projects는 프로젝트 필터를 비워야 한다."""
    import whatwasthat.cli.app as app_module

    project_dir = tmp_data_dir / "myproj"
    project_dir.mkdir()
    monkeypatch.chdir(project_dir)

    captured: dict = {}

    def _fake_collect(*, env, date, source=None, project=None):
        captured["collect"] = {
            "env": env,
            "date": date,
            "source": source,
            "project": project,
        }
        return []

    class _FakeClient:
        def __init__(self, config):
            self.config = config

        def upload_sessions(self, sessions):
            return {"uploaded": len(list(sessions)), "failed": 0, "skipped": 0}

    monkeypatch.setattr(
        "whatwasthat.remote.discovery.collect_sessions_for_date",
        _fake_collect,
    )
    monkeypatch.setattr("whatwasthat.remote.client.RemoteGatewayClient", _FakeClient)

    runner = CliRunner()
    result = runner.invoke(
        app_module.app,
        [
            "remote-ingest",
            "--env",
            "home",
            "--date",
            "2026-05-01",
            "--source",
            "codex-cli",
            "--all-projects",
        ],
    )

    assert result.exit_code == 0, result.output
    assert captured["collect"] == {
        "env": "home",
        "date": "2026-05-01",
        "source": "codex-cli",
        "project": None,
    }


def test_remote_ingest_all_requires_source(monkeypatch):
    """remote-ingest-all은 --source 없이는 실행되면 안 된다."""
    import whatwasthat.cli.app as app_module

    runner = CliRunner()
    result = runner.invoke(app_module.app, ["remote-ingest-all", "--env", "home"])

    assert result.exit_code != 0
    assert "Missing option '--source'" in result.output


def test_remote_ingest_all_uses_source_without_project_filter(tmp_data_dir, monkeypatch):
    """remote-ingest-all은 source를 필수로 받고 전체 프로젝트 범위에서 업로드한다."""
    import whatwasthat.cli.app as app_module

    project_dir = tmp_data_dir / "myproj"
    project_dir.mkdir()
    monkeypatch.chdir(project_dir)

    captured: dict = {}

    def _fake_collect(*, env, source):
        captured["collect"] = {"env": env, "source": source}
        return []

    class _FakeClient:
        def __init__(self, config):
            self.config = config

        def upload_sessions(self, sessions):
            return {"uploaded": len(list(sessions)), "failed": 0, "skipped": 0}

    monkeypatch.setattr(
        "whatwasthat.remote.discovery.collect_all_sessions_for_source",
        _fake_collect,
    )
    monkeypatch.setattr("whatwasthat.remote.client.RemoteGatewayClient", _FakeClient)

    runner = CliRunner()
    result = runner.invoke(
        app_module.app,
        ["remote-ingest-all", "--env", "home", "--source", "gemini-cli"],
    )

    assert result.exit_code == 0, result.output
    assert captured["collect"] == {"env": "home", "source": "gemini-cli"}
