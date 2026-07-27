"""Import Mercado Pago account statement CSV files into Bronze."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from uuid import UUID, uuid4

import pandas as pd
from sqlalchemy import Date, Numeric, Text, text
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID

from home_lab.database import get_engine


CSV_COLUMNS = [
    "RELEASE_DATE",
    "TRANSACTION_TYPE",
    "REFERENCE_ID",
    "TRANSACTION_NET_AMOUNT",
    "PARTIAL_BALANCE",
]

READ_OPTIONS = {
    "sep": ";",
    "skiprows": 3,
    "dtype": str,
    "keep_default_na": False,
}

COLUMN_NAMES = {
    "RELEASE_DATE": "release_date",
    "TRANSACTION_TYPE": "transaction_type",
    "REFERENCE_ID": "reference_id",
    "TRANSACTION_NET_AMOUNT": "transaction_net_amount",
    "PARTIAL_BALANCE": "partial_balance",
}

COLUMN_TYPES = {
    "batch_id": PostgreSQLUUID(as_uuid=True),
    "release_date": Date(),
    "transaction_type": Text(),
    "reference_id": Text(),
    "transaction_net_amount": Numeric(18, 2),
    "partial_balance": Numeric(18, 2),
}


@dataclass(frozen=True)
class ImportResult:
    batch_id: UUID
    source_filename: str
    row_count: int


def file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_csv(path: Path) -> pd.DataFrame:
    if not path.is_file():
        raise FileNotFoundError(path)

    dataframe = pd.read_csv(path, **READ_OPTIONS)
    actual_columns = list(dataframe.columns)
    if actual_columns != CSV_COLUMNS:
        raise ValueError(
            f"Unexpected CSV columns. Expected {CSV_COLUMNS}, got {actual_columns}"
        )
    return dataframe


def _argentine_decimal(series: pd.Series) -> pd.Series:
    normalized = (
        series.str.strip()
        .str.replace(".", "", regex=False)
        .str.replace(",", ".", regex=False)
    )
    return normalized.map(lambda value: Decimal(value) if value else None)


def transform(dataframe: pd.DataFrame) -> pd.DataFrame:
    dataframe = dataframe.rename(columns=COLUMN_NAMES)

    release_dates = dataframe["release_date"].str.strip().replace("", pd.NA)
    dataframe["release_date"] = pd.to_datetime(
        release_dates,
        format="%d-%m-%Y",
        errors="raise",
    ).dt.date

    for column in ("transaction_type", "reference_id"):
        dataframe[column] = dataframe[column].str.strip().replace("", None)

    for column in ("transaction_net_amount", "partial_balance"):
        dataframe[column] = _argentine_decimal(dataframe[column])

    return dataframe


def process(path: Path) -> ImportResult:
    dataframe = transform(read_csv(path))
    source_filename = path.name
    batch_id = uuid4()
    engine = get_engine()

    with engine.begin() as connection:
        connection.execute(
            text(
                """
                DELETE FROM bronze.import_batches
                WHERE source_filename = :source_filename
                """
            ),
            {"source_filename": source_filename},
        )
        connection.execute(
            text(
                """
                INSERT INTO bronze.import_batches (
                    id, source_filename, source_sha256, row_count
                )
                VALUES (:id, :source_filename, :source_sha256, :row_count)
                """
            ),
            {
                "id": batch_id,
                "source_filename": source_filename,
                "source_sha256": file_sha256(path),
                "row_count": len(dataframe),
            },
        )

        rows = dataframe.copy()
        rows.insert(0, "batch_id", batch_id)
        if not rows.empty:
            rows.to_sql(
                name="mercadopago_account_statements",
                con=connection,
                schema="bronze",
                if_exists="append",
                index=False,
                chunksize=1_000,
                dtype=COLUMN_TYPES,
            )

    return ImportResult(batch_id, source_filename, len(dataframe))
