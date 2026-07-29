from decimal import Decimal

import pytest

from home_lab.config import monotributo_annual_limit_ars


def test_optional_monotributo_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MONOTRIBUTO_ANNUAL_LIMIT_ARS", raising=False)
    assert monotributo_annual_limit_ars() is None

    monkeypatch.setenv("MONOTRIBUTO_ANNUAL_LIMIT_ARS", "1000000.50")
    assert monotributo_annual_limit_ars() == Decimal("1000000.50")


def test_monotributo_limit_must_be_positive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MONOTRIBUTO_ANNUAL_LIMIT_ARS", "0")
    with pytest.raises(ValueError, match="must be positive"):
        monotributo_annual_limit_ars()
