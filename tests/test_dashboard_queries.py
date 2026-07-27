from datetime import date

from core.database import get_engine
from dashboard.queries import available_date_range, daily_balance, movements, overview, top_expenses


def test_dashboard_queries_read_imported_account_statement() -> None:
    engine = get_engine()
    date_range = available_date_range(engine)
    assert date_range is not None
    start_date, end_date = date_range

    summary = overview(engine, start_date, end_date)
    assert summary["income"] > 0
    assert summary["expenses"] < 0
    assert not daily_balance(engine, start_date, end_date).empty
    assert not top_expenses(engine, start_date, end_date).empty
    assert not movements(engine, start_date, end_date).empty


def test_movements_filters_by_transaction_type() -> None:
    engine = get_engine()
    data = movements(engine, date(2026, 6, 1), date(2026, 6, 30), "Netflix")
    assert not data.empty
    assert data["transaction_type"].str.contains("Netflix", case=False).all()
