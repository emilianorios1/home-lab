from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import text

from home_lab.database import create_schema, get_engine
from home_lab.mercadopago.importer import (
    CSV_COLUMNS,
    file_sha256,
    process,
    process_api_report,
    read_api_csv,
    read_csv,
    read_summary,
    statement_period,
    transform,
    transform_api,
    validate_statement,
)


def sample_dataframe() -> pd.DataFrame:
    return pd.DataFrame(
        [["01-06-2026", "Pago con QR", "161193543183", "-15.000,00", "116.778,75"]],
        columns=CSV_COLUMNS,
    )


def test_transform_parses_argentine_amounts() -> None:
    record = transform(sample_dataframe()).iloc[0]
    assert str(record["transaction_net_amount"]) == "-15000.00"
    assert str(record["partial_balance"]) == "116778.75"
    assert record["release_date"].isoformat() == "2026-06-01"


def test_statement_period_expands_a_single_month() -> None:
    dataframe = transform(sample_dataframe())
    assert statement_period(dataframe) == (
        pd.Timestamp("2026-06-01").date(),
        pd.Timestamp("2026-06-30").date(),
    )


def test_read_csv_rejects_wrong_columns(tmp_path: Path) -> None:
    path = tmp_path / "bad.csv"
    path.write_text("one\ntwo\nthree\nA;B\nvalue;value\n")
    with pytest.raises(ValueError, match="Unexpected CSV columns"):
        read_csv(path)


def test_file_sha256_is_stable(tmp_path: Path) -> None:
    path = tmp_path / "report.csv"
    path.write_text("report")
    assert file_sha256(path) == file_sha256(path)


def test_transform_api_report_maps_official_columns() -> None:
    content = (
        b"EXTERNAL_REFERENCE;SOURCE_ID;TRANSACTION_TYPE;TRANSACTION_AMOUNT;"
        b"TRANSACTION_DATE;SETTLEMENT_NET_AMOUNT;SETTLEMENT_DATE\n"
        b"order-1;payment-1;SETTLEMENT;1234.50;"
        b"2026-06-01T12:00:00Z;-1200.25;2026-06-02T03:00:00Z\n"
    )
    record = transform_api(read_api_csv(content)).iloc[0]
    assert record["release_date"].isoformat() == "2026-06-02"
    assert record["reference_id"] == "payment-1"
    assert record["transaction_type"] == "SETTLEMENT"
    assert str(record["transaction_net_amount"]) == "-1200.25"
    assert record["partial_balance"] is None


def test_transform_api_prefers_human_readable_description() -> None:
    dataframe = pd.DataFrame(
        [
            {
                "SOURCE_ID": "payment-1",
                "TRANSACTION_TYPE": "PAYOUTS",
                "DESCRIPTION": "Transferencia enviada Bled Cesar Adrian",
                "TRANSACTION_AMOUNT": "-578650.00",
                "TRANSACTION_DATE": "2026-07-10T12:00:00Z",
            }
        ]
    )
    record = transform_api(dataframe).iloc[0]
    assert record["transaction_type"] == "Transferencia enviada Bled Cesar Adrian"


def test_transform_api_uses_the_argentina_calendar_date() -> None:
    dataframe = pd.DataFrame(
        [
            {
                "SOURCE_ID": "payment-near-midnight",
                "TRANSACTION_TYPE": "SETTLEMENT",
                "TRANSACTION_AMOUNT": "1.00",
                "TRANSACTION_DATE": "2026-07-01T02:30:00Z",
            }
        ]
    )
    record = transform_api(dataframe).iloc[0]
    assert record["release_date"].isoformat() == "2026-06-30"


def test_transform_api_falls_back_to_external_reference() -> None:
    dataframe = pd.DataFrame(
        [
            {
                "EXTERNAL_REFERENCE": "transfer-1",
                "TRANSACTION_TYPE": "WITHDRAWAL",
                "TRANSACTION_AMOUNT": "-10,50",
                "TRANSACTION_DATE": "2026-06-01T03:00:00Z",
            }
        ]
    )
    record = transform_api(dataframe).iloc[0]
    assert record["reference_id"] == "transfer-1"
    assert str(record["transaction_net_amount"]) == "-10.50"


def test_import_persists_and_replaces_a_statement_period(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = tmp_path / "statements"
    monkeypatch.setenv("FINANCIAL_STATEMENT_STORE_PATH", str(store))
    source = tmp_path / "integration-account-statement.csv"
    source.write_text(
        "INITIAL_BALANCE;CREDITS;DEBITS;FINAL_BALANCE\n0,00;1,00;-1,00;0,00\n\n"
        + ";".join(CSV_COLUMNS)
        + "\n01-06-2026;Ingreso;1;1,00;1,00\n"
        + "01-06-2026;Pago con QR;2;-1,00;0,00\n"
    )
    engine = get_engine()
    try:
        create_schema(engine)
        first = process(source)
        second = process(source)
        assert first.statement_id == second.statement_id
        assert first.storage_path == second.storage_path
        assert (store / first.storage_path).read_bytes() == source.read_bytes()
        with engine.connect() as connection:
            statement = connection.execute(
                text(
                    """
                    SELECT period_start, period_end, initial_balance, final_balance,
                           row_count, storage_path
                    FROM bronze.financial_statements
                    WHERE id = :statement_id
                    """
                ),
                {"statement_id": first.statement_id},
            ).one()
            row_count = connection.execute(
                text(
                    """
                    SELECT count(*)
                    FROM bronze.mercadopago_statement_movements
                    WHERE statement_id = :statement_id
                    """
                ),
                {"statement_id": first.statement_id},
            ).scalar_one()
        assert statement.period_start.isoformat() == "2026-06-01"
        assert statement.period_end.isoformat() == "2026-06-30"
        assert str(statement.initial_balance) == "0.00"
        assert str(statement.final_balance) == "0.00"
        assert statement.row_count == 2
        assert statement.storage_path == first.storage_path
        assert row_count == 2
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


def test_import_rejects_a_broken_running_balance(tmp_path: Path) -> None:
    source = tmp_path / "broken-account-statement.csv"
    source.write_text(
        "INITIAL_BALANCE;CREDITS;DEBITS;FINAL_BALANCE\n0,00;0,00;-1,00;-1,00\n\n"
        + ";".join(CSV_COLUMNS)
        + "\n01-06-2026;Pago;1;-1,00;-2,00\n"
    )
    dataframe = transform(read_csv(source))
    with pytest.raises(ValueError, match="running balance"):
        validate_statement(dataframe, read_summary(source))


def test_api_report_loads_into_its_own_table() -> None:
    source_filename = "mercadopago-api-integration-separate-source.csv"
    content = (
        b"SOURCE_ID;TRANSACTION_TYPE;TRANSACTION_AMOUNT;TRANSACTION_DATE\n"
        b"api-separate-1;WITHDRAWAL;-10.00;2026-08-01T03:00:00Z\n"
    )
    engine = get_engine()
    try:
        create_schema(engine)
        result = process_api_report(content, source_filename)
        with engine.connect() as connection:
            api_rows = connection.execute(
                text(
                    """
                    SELECT count(*)
                    FROM bronze.mercadopago_api_movements
                    WHERE batch_id = :batch_id
                    """
                ),
                {"batch_id": result.batch_id},
            ).scalar_one()
            legacy_rows = connection.execute(
                text(
                    """
                    SELECT count(*)
                    FROM bronze.mercadopago_account_statements
                    WHERE batch_id = :batch_id
                    """
                ),
                {"batch_id": result.batch_id},
            ).scalar_one()
        assert api_rows == 1
        assert legacy_rows == 0
    finally:
        with engine.begin() as connection:
            connection.execute(
                text("DELETE FROM bronze.import_batches WHERE source_filename = :filename"),
                {"filename": source_filename},
            )
