"""Small pandas helpers shared by CSV pipelines."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy import Connection


def read_csv(
    path: Path,
    *,
    expected_columns: Sequence[str],
    options: Mapping[str, Any] | None = None,
) -> pd.DataFrame:
    """Read a CSV and fail early when its shape is not the expected one."""
    if not path.is_file():
        raise FileNotFoundError(path)

    dataframe = pd.read_csv(path, **(options or {}))
    actual_columns = list(dataframe.columns)
    if actual_columns != list(expected_columns):
        raise ValueError(
            f"Unexpected CSV columns. Expected {list(expected_columns)}, got {actual_columns}"
        )
    return dataframe


def load_dataframe(
    connection: Connection,
    dataframe: pd.DataFrame,
    *,
    schema: str,
    table: str,
    column_types: Mapping[str, Any],
) -> None:
    """Append a dataframe to an existing PostgreSQL table."""
    if dataframe.empty:
        return

    dataframe.to_sql(
        name=table,
        con=connection,
        schema=schema,
        if_exists="append",
        index=False,
        chunksize=1_000,
        dtype=column_types,
    )
