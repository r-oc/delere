from typer.testing import CliRunner

from delere.cli import app

runner = CliRunner()


def test_help_exits_zero():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "delere" in result.output.lower()


def test_redact_help():
    result = runner.invoke(app, ["redact", "--help"])
    assert result.exit_code == 0
    assert "compliance" in result.output.lower()


def test_profiles_list_help():
    result = runner.invoke(app, ["profiles", "list", "--help"])
    assert result.exit_code == 0


def test_config_show_help():
    result = runner.invoke(app, ["config", "show", "--help"])
    assert result.exit_code == 0
