"""Import Mercado Pago account statement CSV files into Bronze."""

from __future__ import annotations

import csv
from calendar import monthrange
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pandas as pd
from sqlalchemy import Date, Numeric, Text, text
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID

from home_lab.config import financial_statement_store_path
from home_lab.database import get_engine
from home_lab.mercadopago.storage import store_statement


ARGENTINA_TIMEZONE = ZoneInfo("America/Argentina/Buenos_Aires")

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

API_COLUMN_TYPES = {
    "batch_id": PostgreSQLUUID(as_uuid=True),
    "release_date": Date(),
    "transaction_type": Text(),
    "reference_id": Text(),
    "transaction_net_amount": Numeric(18, 2),
    "partial_balance": Numeric(18, 2),
}

STATEMENT_COLUMN_TYPES = {
    "statement_id": PostgreSQLUUID(as_uuid=True),
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


@dataclass(frozen=True)
class StatementImportResult:
    statement_id: UUID
    source_filename: str
    row_count: int
    storage_path: str


@dataclass(frozen=True)
class StatementSummary:
    initial_balance: Decimal
    credits: Decimal
    debits: Decimal
    final_balance: Decimal


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


def read_summary(path: Path) -> StatementSummary:
    if not path.is_file():
        raise FileNotFoundError(path)

    with path.open(encoding="utf-8-sig", newline="") as source:
        rows = csv.reader(source, delimiter=";")
        try:
            columns = next(rows)
            values = next(rows)
        except StopIteration as error:
            raise ValueError("Account statement has no balance summary") from error

    expected = ["INITIAL_BALANCE", "CREDITS", "DEBITS", "FINAL_BALANCE"]
    if columns != expected or len(values) != len(expected):
        raise ValueError(
            f"Unexpected account statement summary. Expected {expected}, got {columns}"
        )
    parsed = [_argentine_value(value) for value in values]
    if any(value is None for value in parsed):
        raise ValueError("Account statement balance summary cannot contain empty values")
    return StatementSummary(*parsed)  # type: ignore[arg-type]


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


def _argentine_value(value: str) -> Decimal | None:
    normalized = value.strip().replace(".", "").replace(",", ".")
    return Decimal(normalized) if normalized else None


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


def statement_period(dataframe: pd.DataFrame) -> tuple[date, date]:
    if dataframe.empty:
        raise ValueError("Account statement has no movements")
    first = dataframe["release_date"].min()
    last = dataframe["release_date"].max()
    if first.year == last.year and first.month == last.month:
        return (
            first.replace(day=1),
            last.replace(day=monthrange(last.year, last.month)[1]),
        )
    return first, last


def validate_statement(
    dataframe: pd.DataFrame,
    summary: StatementSummary,
) -> None:
    credits = sum(
        (
            value
            for value in dataframe["transaction_net_amount"]
            if value is not None and value > 0
        ),
        Decimal("0"),
    )
    debits = sum(
        (
            value
            for value in dataframe["transaction_net_amount"]
            if value is not None and value < 0
        ),
        Decimal("0"),
    )
    if credits != summary.credits or debits != summary.debits:
        raise ValueError(
            "Account statement movement totals do not match its balance summary"
        )
    if summary.initial_balance + credits + debits != summary.final_balance:
        raise ValueError("Account statement opening and closing balances do not reconcile")

    running_balance = summary.initial_balance
    for line_number, row in enumerate(dataframe.itertuples(index=False), start=1):
        running_balance += row.transaction_net_amount
        if running_balance != row.partial_balance:
            raise ValueError(
                "Account statement running balance does not reconcile "
                f"at movement line {line_number}"
            )


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
    transaction_types = dataframe["TRANSACTION_TYPE"].str.strip()
    descriptions = dataframe.get(
        "DESCRIPTION", pd.Series("", index=dataframe.index)
    ).str.strip()
    result = pd.DataFrame(
        {
            "release_date": pd.to_datetime(
                release_dates,
                errors="raise",
                utc=True,
            )
            .dt.tz_convert(ARGENTINA_TIMEZONE)
            .dt.date,
            # DESCRIPTION is the human-readable operation detail needed for
            # household-expense categorization. Older configured reports did
            # not include it, so retain TRANSACTION_TYPE as a safe fallback.
            "transaction_type": descriptions.where(
                descriptions != "",
                transaction_types,
            ).replace("", None),
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


def _load_api(
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
                name="mercadopago_api_movements",
                con=connection,
                schema="bronze",
                if_exists="append",
                index=False,
                chunksize=1_000,
                dtype=API_COLUMN_TYPES,
            )

    return ImportResult(batch_id, source_filename, len(dataframe))


def process(
    path: Path,
    *,
    storage_root: Path | None = None,
) -> StatementImportResult:
    dataframe = transform(read_csv(path))
    summary = read_summary(path)
    validate_statement(dataframe, summary)
    period_start, period_end = statement_period(dataframe)
    content = path.read_bytes()
    stored = store_statement(
        storage_root or financial_statement_store_path(),
        provider="mercadopago",
        period_start=period_start,
        content=content,
        suffix=path.suffix or ".csv",
    )
    statement_id = uuid4()
    engine = get_engine()

    with engine.begin() as connection:
        statement_id = connection.execute(
            text(
                """
                INSERT INTO bronze.financial_statements (
                    id, provider, account_key, statement_type,
                    period_start, period_end, source_filename, source_format,
                    source_sha256, storage_path, byte_size,
                    initial_balance, credits, debits, final_balance, row_count
                )
                VALUES (
                    :id, 'mercadopago', 'primary', 'account_statement',
                    :period_start, :period_end, :source_filename, 'csv',
                    :source_sha256, :storage_path, :byte_size,
                    :initial_balance, :credits, :debits, :final_balance, :row_count
                )
                ON CONFLICT (
                    provider, account_key, statement_type, period_start, period_end
                )
                DO UPDATE SET
                    source_filename = excluded.source_filename,
                    source_format = excluded.source_format,
                    source_sha256 = excluded.source_sha256,
                    storage_path = excluded.storage_path,
                    byte_size = excluded.byte_size,
                    initial_balance = excluded.initial_balance,
                    credits = excluded.credits,
                    debits = excluded.debits,
                    final_balance = excluded.final_balance,
                    row_count = excluded.row_count,
                    imported_at = now()
                RETURNING id
                """
            ),
            {
                "id": statement_id,
                "period_start": period_start,
                "period_end": period_end,
                "source_filename": path.name,
                "source_sha256": stored.sha256,
                "storage_path": stored.relative_path,
                "byte_size": stored.byte_size,
                "initial_balance": summary.initial_balance,
                "credits": summary.credits,
                "debits": summary.debits,
                "final_balance": summary.final_balance,
                "row_count": len(dataframe),
            },
        ).scalar_one()

        connection.execute(
            text(
                """
                DELETE FROM bronze.mercadopago_statement_movements
                WHERE statement_id = :statement_id
                """
            ),
            {"statement_id": statement_id},
        )
        rows = dataframe.copy()
        rows.insert(0, "line_number", range(1, len(rows) + 1))
        rows.insert(0, "statement_id", statement_id)
        rows.to_sql(
            name="mercadopago_statement_movements",
            con=connection,
            schema="bronze",
            if_exists="append",
            index=False,
            chunksize=1_000,
            dtype=STATEMENT_COLUMN_TYPES,
        )

    return StatementImportResult(
        statement_id,
        path.name,
        len(dataframe),
        stored.relative_path,
    )


def process_api_report(content: bytes, source_filename: str) -> ImportResult:
    return _load_api(
        transform_api(read_api_csv(content)),
        source_filename=source_filename,
        source_sha256=content_sha256(content),
    )
