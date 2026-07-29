from collections.abc import Iterator
from datetime import date
from decimal import Decimal
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
from home_lab.dashboard.rents import calculate_net_rent, save_monthly_rent
from home_lab.database import create_schema, get_engine
from home_lab.mercadopago.importer import (
    CSV_COLUMNS,
    process,
    process_api_report,
)


@pytest.fixture(scope="module", autouse=True)
def build_analytics_models(
    tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[None]:
    engine = get_engine()
    create_schema(engine)
    source = tmp_path_factory.mktemp("dashboard") / "dashboard-statement.csv"
    source.write_text(
        "INITIAL_BALANCE;CREDITS;DEBITS;FINAL_BALANCE\n"
        "0,00;100,00;-50,00;50,00\n\n"
        + ";".join(CSV_COLUMNS)
        + "\n01-06-2026;Transferencia recibida;dashboard-income;100,00;100,00\n"
        + "02-06-2026;Pago Netflix;dashboard-netflix;-25,00;75,00\n"
        + "03-06-2026;Transferencia enviada Bled Cesar Adrian;"
        "dashboard-rent;-25,00;50,00\n"
    )
    statement = process(source, storage_root=source.parent / "statement-store")
    assert run_transform()
    yield
    with engine.begin() as connection:
        connection.execute(
            text("DELETE FROM bronze.financial_statements WHERE id = :id"),
            {"id": statement.statement_id},
        )


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
        process(source, storage_root=tmp_path / "statement-store")
        data = movements(engine, date(2026, 7, 15), date(2026, 7, 15), "Bled Cesar Adrian")
        test_movement = data[data["reference_id"] == "test-rent"]
        assert len(test_movement) == 1
        assert test_movement.iloc[0]["category"] == "Alquiler"
    finally:
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    DELETE FROM bronze.financial_statements
                    WHERE source_filename = :filename
                    """
                ),
                {"filename": source.name},
            )


def test_statement_replaces_api_rows_inside_its_period(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = get_engine()
    api_filename = "mercadopago-api-coverage-test.csv"
    api_content = (
        b"SOURCE_ID;TRANSACTION_TYPE;TRANSACTION_AMOUNT;TRANSACTION_DATE\n"
        b"coverage-api-id;WITHDRAWAL;-42.00;2026-08-12T03:00:00Z\n"
    )
    statement = tmp_path / "coverage-account-statement.csv"
    statement.write_text(
        "INITIAL_BALANCE;CREDITS;DEBITS;FINAL_BALANCE\n"
        "100,00;0,00;-42,00;58,00\n\n"
        + ";".join(CSV_COLUMNS)
        + "\n12-08-2026;Transferencia enviada Comercio Descriptivo;"
        "coverage-statement-id;-42,00;58,00\n"
    )
    monkeypatch.setenv(
        "FINANCIAL_STATEMENT_STORE_PATH",
        str(tmp_path / "statement-store"),
    )

    api_result = None
    statement_result = None
    try:
        api_result = process_api_report(api_content, api_filename)
        statement_result = process(statement)
        with engine.connect() as connection:
            canonical = connection.execute(
                text(
                    """
                    SELECT source_origin, reference_id, description, amount
                    FROM silver.movements
                    WHERE release_date = date '2026-08-12'
                      AND amount = -42.00
                    """
                )
            ).mappings().all()
        assert len(canonical) == 1
        assert canonical[0]["source_origin"] == "statement"
        assert canonical[0]["reference_id"] == "coverage-statement-id"
        assert canonical[0]["description"] == (
            "Transferencia enviada Comercio Descriptivo"
        )
    finally:
        with engine.begin() as connection:
            if statement_result is not None:
                connection.execute(
                    text(
                        """
                        DELETE FROM bronze.financial_statements
                        WHERE id = :statement_id
                        """
                    ),
                    {"statement_id": statement_result.statement_id},
                )
            if api_result is not None:
                connection.execute(
                    text(
                        """
                        DELETE FROM bronze.import_batches
                        WHERE id = :batch_id
                        """
                    ),
                    {"batch_id": api_result.batch_id},
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
        "Expensas totales",
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


def test_manual_gross_rent_calculates_net_amount() -> None:
    engine = get_engine()
    month = date(2099, 12, 1)
    try:
        saved = save_monthly_rent(engine, month, Decimal("12345.678"))
        summary = monthly_shared_expenses(engine, month)

        assert saved == Decimal("12345.68")
        assert month in shared_expense_months(engine)
        assert summary["rent"] == {
            "gross": Decimal("12345.68"),
            "extraordinary": Decimal("0"),
            "net": Decimal("12345.68"),
            "paid": Decimal("0"),
            "configured": True,
        }
        assert summary["shared_total"] == Decimal("12345.68")
        assert summary["paid_total"] == Decimal("0")
        assert summary["pending_total"] == Decimal("12345.68")
        save_monthly_rent(engine, month, saved)
        with engine.connect() as connection:
            row_count = connection.execute(
                text(
                    """
                    SELECT count(*)
                    FROM bronze.manual_monthly_rents
                    WHERE summary_month = :month
                    """
                ),
                {"month": month},
            ).scalar_one()
        assert row_count == 1
    finally:
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    DELETE FROM bronze.manual_monthly_rents
                    WHERE summary_month = :month
                    """
                ),
                {"month": month},
            )


def test_net_rent_discounts_extraordinary_expenses() -> None:
    assert calculate_net_rent(
        Decimal("500000"),
        Decimal("25000"),
    ) == Decimal("475000")


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
