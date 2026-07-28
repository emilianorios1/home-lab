"""Import Mercado Pago account statement CSV files into Bronze."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from hashlib import sha256
from io import BytesIO
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


def content_sha256(content: bytes) -> str:
    return sha256(content).hexdigest()


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


def read_api_csv(content: bytes) -> pd.DataFrame:
    """Read the configurable CSV returned by the Account Money Reports API."""
    dataframe = pd.read_csv(
        BytesIO(content),
        sep=None,
        engine="python",
        dtype=str,
        keep_default_na=False,
    )
    required = {"TRANSACTION_TYPE", "TRANSACTION_AMOUNT"}
    if not required.issubset(dataframe.columns):
        raise ValueError(
            "Unexpected Mercado Pago API report columns. "
            f"Required {sorted(required)}, got {list(dataframe.columns)}"
        )
    if not {"SETTLEMENT_DATE", "TRANSACTION_DATE"}.intersection(dataframe.columns):
        raise ValueError("Mercado Pago API report has no transaction date column")
    return dataframe


def _argentine_decimal(series: pd.Series) -> pd.Series:
    normalized = (
        series.str.strip()
        .str.replace(".", "", regex=False)
        .str.replace(",", ".", regex=False)
    )
    return normalized.map(lambda value: Decimal(value) if value else None)


def _api_decimal(value: str) -> Decimal | None:
    value = value.strip()
    if not value:
        return None
    if "," in value and "." in value:
        value = value.replace(".", "").replace(",", ".")
    elif "," in value:
        value = value.replace(",", ".")
    return Decimal(value)


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


def transform_api(dataframe: pd.DataFrame) -> pd.DataFrame:
    transaction_dates = dataframe["TRANSACTION_DATE"].str.strip()
    if "SETTLEMENT_DATE" in dataframe.columns:
        settlement_dates = dataframe["SETTLEMENT_DATE"].str.strip()
        release_dates = settlement_dates.where(
            settlement_dates != "",
            transaction_dates,
        )
    else:
        release_dates = transaction_dates
    transaction_amounts = dataframe["TRANSACTION_AMOUNT"].str.strip()
    if "SETTLEMENT_NET_AMOUNT" in dataframe.columns:
        settlement_amounts = dataframe["SETTLEMENT_NET_AMOUNT"].str.strip()
        amounts = settlement_amounts.where(
            settlement_amounts != "",
            transaction_amounts,
        )
    else:
        amounts = transaction_amounts
    result = pd.DataFrame(
        {
            "release_date": pd.to_datetime(
                release_dates,
                errors="raise",
                utc=True,
            ).dt.date,
            "transaction_type": dataframe["TRANSACTION_TYPE"]
            .str.strip()
            .replace("", None),
            "transaction_net_amount": amounts.map(_api_decimal),
            # The official report has no running-balance field.
            "partial_balance": None,
        }
    )
    source_id = dataframe.get("SOURCE_ID", pd.Series("", index=dataframe.index))
    external_reference = dataframe.get(
        "EXTERNAL_REFERENCE", pd.Series("", index=dataframe.index)
    )
    result["reference_id"] = source_id.str.strip().where(
        source_id.str.strip() != "",
        external_reference.str.strip(),
    )
    result["reference_id"] = result["reference_id"].replace("", None)
    return result[
        [
            "release_date",
            "transaction_type",
            "reference_id",
            "transaction_net_amount",
            "partial_balance",
        ]
    ]


def _load(
    dataframe: pd.DataFrame,
    *,
    source_filename: str,
    source_sha256: str,
) -> ImportResult:
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
                "source_sha256": source_sha256,
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


def process(path: Path) -> ImportResult:
    return _load(
        transform(read_csv(path)),
        source_filename=path.name,
        source_sha256=file_sha256(path),
    )


def process_api_report(content: bytes, source_filename: str) -> ImportResult:
    return _load(
        transform_api(read_api_csv(content)),
        source_filename=source_filename,
        source_sha256=content_sha256(content),
    )
