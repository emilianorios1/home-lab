import pytest

from home_lab.siat.client import (
    SiatError,
    TgiPeriod,
    parse_account_id,
    parse_selectable_periods,
)


def test_parses_selectable_tgi_periods() -> None:
    html = """
    <input type="checkbox" name="listIdPeriodoSelected" value="2026.9-1">
    <input type="checkbox" name="listIdPeriodoSelected" value="2026.8-1">
    <input type="checkbox" disabled="disabled">
    """

    assert parse_selectable_periods(html) == (
        TgiPeriod(2026, 8, "2026.8-1"),
        TgiPeriod(2026, 9, "2026.9-1"),
    )


def test_parses_internal_account_id() -> None:
    html = '<input type="hidden" name="cuentaId" value="86900" />'
    assert parse_account_id(html) == "86900"


def test_rejects_missing_internal_account_id() -> None:
    with pytest.raises(SiatError, match="account id"):
        parse_account_id("<html></html>")
