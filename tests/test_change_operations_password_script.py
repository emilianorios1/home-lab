import os
import stat
import subprocess
from pathlib import Path

from dotenv import dotenv_values


SCRIPT = Path(__file__).parents[1] / "scripts" / "change-operations-password.sh"


def test_changes_operations_password_without_printing_it(tmp_path: Path) -> None:
    prod_env = tmp_path / "prod.env"
    prod_env.write_text(
        "KEEP_THIS=value\nHOME_LAB_OPERATIONS_PASSWORD=old-password\n",
        encoding="utf-8",
    )
    prod_env.chmod(0o600)

    compose_command = tmp_path / "production-compose.sh"
    compose_command.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    compose_command.chmod(compose_command.stat().st_mode | stat.S_IXUSR)

    password = "new pass' $value#\\"
    result = subprocess.run(
        [str(SCRIPT)],
        check=True,
        env={**os.environ, "HOME_LAB_CONFIG_DIR": str(tmp_path)},
        input=f"{password}\n",
        capture_output=True,
        text=True,
    )

    assert password not in result.stdout
    assert dotenv_values(prod_env)["HOME_LAB_OPERATIONS_PASSWORD"] == password
    assert dotenv_values(prod_env)["KEEP_THIS"] == "value"
    assert stat.S_IMODE(prod_env.stat().st_mode) == 0o600
