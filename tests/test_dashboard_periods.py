from datetime import date

from home_lab.dashboard.periods import month_bounds, month_label, months_between


def test_months_between_includes_every_month_across_years() -> None:
    assert months_between(date(2025, 11, 20), date(2026, 2, 3)) == [
        date(2025, 11, 1),
        date(2025, 12, 1),
        date(2026, 1, 1),
        date(2026, 2, 1),
    ]


def test_month_display_and_bounds() -> None:
    assert month_label(date(2024, 2, 15)) == "Febrero 2024"
    assert month_bounds(date(2024, 2, 15)) == (
        date(2024, 2, 1),
        date(2024, 2, 29),
    )
