"""Raw Mercado Pago account statement CSV import."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from pathlib import Path
from uuid import UUID, uuid4

import pandas as pd
from sqlalchemy import Engine, text

from core.database import create_schema


CSV_COLUMNS = [
    "RELEASE_DATE",
    "TRANSACTION_TYPE",
    "REFERENCE_ID",
    "TRANSACTION_NET_AMOUNT",
    "PARTIAL_BALANCE",
]


@dataclass(frozen=True)
class ImportResult:
    batch_id: UUID
    source_filename: str
    row_count: int


def read_csv(path: Path) -> pd.DataFrame:
    if not path.is_file():
        raise FileNotFoundError(path)
    dataframe = pd.read_csv(path, sep=";", skiprows=3, dtype=str, keep_default_na=False)
    if list(dataframe.columns) != CSV_COLUMNS:
        raise ValueError(
            "Unexpected account statement CSV columns. "
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
        return Decimal(value.replace(".", "").replace(",", "."))
    except InvalidOperation as error:
        raise ValueError(f"Invalid {column} at CSV row {row_number}: {value!r}") from error


def _date(value: str, row_number: int) -> date | None:
    value = value.strip()
    if not value:
        return None
    try:
        return datetime.strptime(value, "%d-%m-%Y").date()
    except ValueError as error:
        raise ValueError(f"Invalid RELEASE_DATE at CSV row {row_number}: {value!r}") from error


def normalize(dataframe: pd.DataFrame) -> list[dict[str, object | None]]:
    records: list[dict[str, object | None]] = []
    for row_number, row in enumerate(dataframe.to_dict(orient="records"), start=5):
        records.append(
            {
                "release_date": _date(row["RELEASE_DATE"], row_number),
                "transaction_type": _optional_text(row["TRANSACTION_TYPE"]),
                "reference_id": _optional_text(row["REFERENCE_ID"]),
                "transaction_net_amount": _decimal(
                    row["TRANSACTION_NET_AMOUNT"], "TRANSACTION_NET_AMOUNT", row_number
                ),
                "partial_balance": _decimal(row["PARTIAL_BALANCE"], "PARTIAL_BALANCE", row_number),
            }
        )
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
                    INSERT INTO raw.mercadopago_account_statements (
                        batch_id, release_date, transaction_type, reference_id,
                        transaction_net_amount, partial_balance
                    ) VALUES (
                        :batch_id, :release_date, :transaction_type, :reference_id,
                        :transaction_net_amount, :partial_balance
                    )
                    """
                ),
                records,
            )
    return ImportResult(batch_id=batch_id, source_filename=source_filename, row_count=len(records))
