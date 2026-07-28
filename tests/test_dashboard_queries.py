from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import text

from home_lab.cli import run_transform
from home_lab.dashboard.queries import (
    available_date_range,
    credit_card_expenses,
    credit_card_expenses_by_category,
    credit_card_statements,
    daily_balance,
    expenses_by_category,
    monthly_shared_expenses,
    movements,
    overview,
    shared_expense_months,
)
from home_lab.database import create_schema, get_engine
from home_lab.mercadopago.importer import CSV_COLUMNS, process


@pytest.fixture(scope="module", autouse=True)
def build_analytics_models() -> None:
    create_schema(get_engine())
    assert run_transform()


def test_dashboard_queries_read_imported_account_statement() -> None:
    engine = get_engine()
    date_range = available_date_range(engine)
    assert date_range is not None
    start_date, end_date = date_range

    summary = overview(engine, start_date, end_date)
    assert summary["income"] > 0
    assert summary["expenses"] < 0
    assert not daily_balance(engine, start_date, end_date).empty
    assert not expenses_by_category(engine, start_date, end_date).empty
    movement_data = movements(engine, start_date, end_date)
    assert not movement_data.empty
    assert "category" in movement_data.columns


def test_movements_filters_by_transaction_type() -> None:
    engine = get_engine()
    data = movements(engine, date(2026, 6, 1), date(2026, 6, 30), "Netflix")
    assert not data.empty
    assert data["transaction_type"].str.contains("Netflix", case=False).all()


def test_bled_cesar_adrian_expenses_are_rent(tmp_path: Path) -> None:
    engine = get_engine()
    source = tmp_path / "bled-category-test.csv"
    source.write_text(
        "INITIAL_BALANCE;CREDITS;DEBITS;FINAL_BALANCE\n"
        "0,00;0,00;-100,00;-100,00\n\n"
        + ";".join(CSV_COLUMNS)
        + "\n15-07-2026;Transferencia enviada Bled Cesar Adrian;test-rent;-100,00;-100,00\n"
    )
    try:
        process(source)
        data = movements(engine, date(2026, 7, 15), date(2026, 7, 15), "Bled Cesar Adrian")
        test_movement = data[data["reference_id"] == "test-rent"]
        assert len(test_movement) == 1
        assert test_movement.iloc[0]["category"] == "Alquiler"
    finally:
        with engine.begin() as connection:
            connection.execute(
                text("DELETE FROM bronze.import_batches WHERE source_filename = :filename"),
                {"filename": source.name},
            )


def test_monthly_shared_expenses_have_monthly_summary_shape() -> None:
    engine = get_engine()
    months = shared_expense_months(engine)
    assert months
    summary = monthly_shared_expenses(engine, months[0])
    rows = summary["rows"]
    services = summary["services"]
    assert list(rows["concept"]) == [
        "Alquiler bruto",
        "Expensas extraordinarias",
        "Expensas a pagar",
        "Alquiler a pagar",
        "Luz",
        "Agua",
        "Gas",
        "TGI",
    ]
    assert list(services["category"]) == ["Expensas", "Luz", "Agua", "Gas", "TGI"]
    assert summary["rent"]["gross"] == (
        summary["rent"]["net"] + summary["rent"]["extraordinary"]
    )
    assert summary["pending_total"] == max(
        summary["shared_total"] - summary["paid_total"],
        0,
    )
    assert 0 <= summary["payment_progress"] <= 1
    assert abs(summary["per_person"] - summary["shared_total"] / 2) <= 0.005


def test_credit_card_queries_have_expected_shape() -> None:
    engine = get_engine()
    expenses = credit_card_expenses(
        engine,
        date(2026, 1, 1),
        date(2026, 12, 31),
    )
    categories = credit_card_expenses_by_category(
        engine,
        date(2026, 1, 1),
        date(2026, 12, 31),
    )
    statements = credit_card_statements(
        engine,
        date(2026, 1, 1),
        date(2026, 12, 31),
    )
    assert {
        "purchase_date",
        "category",
        "description",
        "currency",
        "amount",
    }.issubset(expenses.columns)
    assert {"category", "amount"}.issubset(categories.columns)
    assert {
        "period",
        "due_date",
        "total_amount",
        "foreign_total_amount",
    }.issubset(statements.columns)
