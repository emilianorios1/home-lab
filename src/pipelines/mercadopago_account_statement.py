"""Mercado Pago account statement CSV pipeline."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pandas as pd
from sqlalchemy import Date, Numeric, Text

from core.core import ImportResult, run_csv_pipeline
from core.etl import read_csv as read_csv_file


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
    "release_date": Date(),
    "transaction_type": Text(),
    "reference_id": Text(),
    "transaction_net_amount": Numeric(18, 2),
    "partial_balance": Numeric(18, 2),
}


def read_csv(path: Path) -> pd.DataFrame:
    return read_csv_file(path, expected_columns=CSV_COLUMNS, options=READ_OPTIONS)


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
    return run_csv_pipeline(
        path,
        table="mercadopago_account_statements",
        expected_columns=CSV_COLUMNS,
        read_options=READ_OPTIONS,
        transform=transform,
        column_types=COLUMN_TYPES,
    )
