"""Raw Mercado Pago settlement CSV import."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from pathlib import Path
from uuid import UUID, uuid4

import pandas as pd
from sqlalchemy import Engine, text

from core.database import create_schema


CSV_COLUMNS = [
    "SOURCE_ID",
    "PAYMENT_METHOD_TYPE",
    "TRANSACTION_TYPE",
    "TRANSACTION_AMOUNT",
    "TRANSACTION_DATE",
    "FEE_AMOUNT",
    "SETTLEMENT_DATE",
    "REAL_AMOUNT",
    "TAXES_AMOUNT",
    "BUSINESS_UNIT",
    "SUB_UNIT",
    "MONEY_RELEASE_DATE",
]
DECIMAL_COLUMNS = {"TRANSACTION_AMOUNT", "FEE_AMOUNT", "REAL_AMOUNT", "TAXES_AMOUNT"}
DATETIME_COLUMNS = {"TRANSACTION_DATE", "SETTLEMENT_DATE", "MONEY_RELEASE_DATE"}
DATABASE_COLUMNS = [column.lower() for column in CSV_COLUMNS]


@dataclass(frozen=True)
class ImportResult:
    batch_id: UUID
    source_filename: str
    row_count: int


def read_csv(path: Path) -> pd.DataFrame:
    if not path.is_file():
        raise FileNotFoundError(path)
    dataframe = pd.read_csv(path, dtype=str, keep_default_na=False)
    if list(dataframe.columns) != CSV_COLUMNS:
        raise ValueError(
            "Unexpected Mercado Pago CSV columns. "
            f"Expected {CSV_COLUMNS}, got {list(dataframe.columns)}"
        )
    return dataframe


def _optional_text(value: str) -> str | None:
    value = value.strip()
    return value or None


def _decimal(value: str, column: str, row_number: int) -> Decimal | None:
    value = value.strip()
    if not value:
        return None
    try:
        return Decimal(value)
    except InvalidOperation as error:
        raise ValueError(f"Invalid {column} at CSV row {row_number}: {value!r}") from error


def _datetime(value: str, column: str, row_number: int) -> datetime | None:
    value = value.strip()
    if not value:
        return None
    parsed = pd.to_datetime(value, utc=True, errors="coerce")
    if pd.isna(parsed):
        raise ValueError(f"Invalid {column} at CSV row {row_number}: {value!r}")
    return parsed.to_pydatetime()


def normalize(dataframe: pd.DataFrame) -> list[dict[str, object | None]]:
    records: list[dict[str, object | None]] = []
    for row_number, row in enumerate(dataframe.to_dict(orient="records"), start=2):
        record: dict[str, object | None] = {}
        for column in CSV_COLUMNS:
            value = row[column]
            if column in DECIMAL_COLUMNS:
                record[column.lower()] = _decimal(value, column, row_number)
            elif column in DATETIME_COLUMNS:
                record[column.lower()] = _datetime(value, column, row_number)
            else:
                record[column.lower()] = _optional_text(value)
        records.append(record)
    return records


def file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def import_csv(engine: Engine, path: Path) -> ImportResult:
    dataframe = read_csv(path)
    records = normalize(dataframe)
    source_filename = path.name
    batch_id = uuid4()

    create_schema(engine)
    with engine.begin() as connection:
        connection.execute(
            text("DELETE FROM raw.import_batches WHERE source_filename = :source_filename"),
            {"source_filename": source_filename},
        )
        connection.execute(
            text(
                """
                INSERT INTO raw.import_batches (id, source_filename, source_sha256, row_count)
                VALUES (:id, :source_filename, :source_sha256, :row_count)
                """
            ),
            {
                "id": batch_id,
                "source_filename": source_filename,
                "source_sha256": file_sha256(path),
                "row_count": len(records),
            },
        )
        if records:
            for record in records:
                record["batch_id"] = batch_id
            connection.execute(
                text(
                    """
                    INSERT INTO raw.mercadopago_settlements (
                        batch_id, source_id, payment_method_type, transaction_type,
                        transaction_amount, transaction_date, fee_amount, settlement_date,
                        real_amount, taxes_amount, business_unit, sub_unit, money_release_date
                    ) VALUES (
                        :batch_id, :source_id, :payment_method_type, :transaction_type,
                        :transaction_amount, :transaction_date, :fee_amount, :settlement_date,
                        :real_amount, :taxes_amount, :business_unit, :sub_unit, :money_release_date
                    )
                    """
                ),
                records,
            )
    return ImportResult(batch_id=batch_id, source_filename=source_filename, row_count=len(records))
