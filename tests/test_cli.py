from pathlib import Path

import pytest

from home_lab import cli


def test_resolve_dbt_project_dir_from_checkout_when_installed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checkout = tmp_path / "checkout"
    project_dir = checkout / "dbt"
    project_dir.mkdir(parents=True)
    (project_dir / "dbt_project.yml").touch()

    installed_cli = (
        tmp_path
        / "venv"
        / "lib"
        / "python3.12"
        / "site-packages"
        / "home_lab"
        / "cli.py"
    )
    monkeypatch.delenv("HOME_LAB_DBT_PROJECT_DIR", raising=False)
    monkeypatch.setattr(cli, "__file__", str(installed_cli))
    monkeypatch.chdir(checkout)

    assert cli.resolve_dbt_project_dir() == project_dir.resolve()
