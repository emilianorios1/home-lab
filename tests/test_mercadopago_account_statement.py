from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import text

from home_lab.database import create_schema, get_engine
from home_lab.mercadopago.importer import (
    CSV_COLUMNS,
    file_sha256,
    process,
    read_api_csv,
    read_csv,
    transform,
    transform_api,
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


def test_import_replaces_a_batch_with_the_same_filename(tmp_path: Path) -> None:
    source = tmp_path / "integration-account-statement.csv"
    source.write_text(
        "INITIAL_BALANCE;CREDITS;DEBITS;FINAL_BALANCE\n0,00;1,00;-1,00;0,00\n\n"
        + ";".join(CSV_COLUMNS)
        + "\n01-06-2026;Pago con QR;1;-10,25;20,00\n"
    )
    engine = get_engine()
    try:
        create_schema(engine)
        first = process(source)
        second = process(source)
        assert first.batch_id != second.batch_id
        with engine.connect() as connection:
            batch_count = connection.execute(
                text("SELECT count(*) FROM bronze.import_batches WHERE source_filename = :filename"),
                {"filename": source.name},
            ).scalar_one()
            row_count = connection.execute(
                text(
                    """
                    SELECT count(*) FROM bronze.mercadopago_account_statements statements
                    JOIN bronze.import_batches batches ON batches.id = statements.batch_id
                    WHERE batches.source_filename = :filename
                    """
                ),
                {"filename": source.name},
            ).scalar_one()
        assert batch_count == 1
        assert row_count == 1
    finally:
        with engine.begin() as connection:
            connection.execute(
                text("DELETE FROM bronze.import_batches WHERE source_filename = :filename"),
                {"filename": source.name},
            )
