import os
import stat
import subprocess
from pathlib import Path

import pytest
from dotenv import dotenv_values


SCRIPT = Path(__file__).parents[1] / "scripts" / "set-afip-sdk-access-token.sh"


@pytest.mark.parametrize("current_token", [None, "old-token"])
def test_sets_afip_sdk_access_token_without_printing_it(
    tmp_path: Path,
    current_token: str | None,
) -> None:
    prod_env = tmp_path / "prod.env"
    contents = "KEEP_THIS=value\n"
    if current_token is not None:
        contents += f"AFIP_SDK_ACCESS_TOKEN={current_token}\n"
    prod_env.write_text(contents, encoding="utf-8")
    prod_env.chmod(0o640)

    compose_command = tmp_path / "production-compose.sh"
    compose_command.write_text(
        "#!/usr/bin/env bash\nprintf '%s\\n' \"$@\" > \"$HOME_LAB_CONFIG_DIR/compose.args\"\n",
        encoding="utf-8",
    )
    compose_command.chmod(compose_command.stat().st_mode | stat.S_IXUSR)

    access_token = "new token' $value#\\"
    result = subprocess.run(
        [str(SCRIPT)],
        check=True,
        env={**os.environ, "HOME_LAB_CONFIG_DIR": str(tmp_path)},
        input=f"{access_token}\n",
        capture_output=True,
        text=True,
    )

    assert access_token not in result.stdout
    assert access_token not in result.stderr
    assert dotenv_values(prod_env)["AFIP_SDK_ACCESS_TOKEN"] == access_token
    assert dotenv_values(prod_env)["KEEP_THIS"] == "value"
    assert stat.S_IMODE(prod_env.stat().st_mode) == 0o600
    assert (tmp_path / "compose.args").read_text(encoding="utf-8").splitlines() == [
        "up",
        "-d",
        "--force-recreate",
        "dashboard",
    ]
