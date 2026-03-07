from __future__ import annotations

from typer.testing import CliRunner

from scheduler.cli import app


def test_web_command_defaults_to_all_interfaces(monkeypatch, tmp_path):
    captured: dict[str, object] = {}
    database_path = tmp_path / "scheduler.db"
    report_dir = tmp_path / "reports"
    log_dir = tmp_path / "logs"

    def fake_create_app(settings):
        captured["database_url"] = settings.expanded_database_url
        return object()

    def fake_run(web_app, host: str, port: int):
        captured["web_app"] = web_app
        captured["host"] = host
        captured["port"] = port

    monkeypatch.setattr("scheduler.web_app.create_app", fake_create_app)
    monkeypatch.setattr("uvicorn.run", fake_run)

    config_path = tmp_path / ".scheduler.toml"
    config_path.write_text(
        "\n".join(
            [
                f'database_url = "sqlite:///{database_path}"',
                f'report_output_dir = "{report_dir}"',
                f'log_dir = "{log_dir}"',
                'auth_secret = "test-secret"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    runner = CliRunner()
    result = runner.invoke(app, ["--config", str(config_path), "web"])

    assert result.exit_code == 0
    assert "Web 已启动: http://0.0.0.0:8787" in result.stdout
    assert captured["host"] == "0.0.0.0"
    assert captured["port"] == 8787
