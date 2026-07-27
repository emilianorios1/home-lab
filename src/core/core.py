"""Generic CSV-to-PostgreSQL pipeline runner."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pandas as pd
from sqlalchemy import Engine, text
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID

from core.database import get_engine
from core.etl import load_dataframe, read_csv


Transform = Callable[[pd.DataFrame], pd.DataFrame]


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


def run_csv_pipeline(
    path: Path,
    *,
    table: str,
    expected_columns: Sequence[str],
    transform: Transform,
    read_options: Mapping[str, Any] | None = None,
    column_types: Mapping[str, Any] | None = None,
    schema: str = "bronze",
) -> ImportResult:
    """Read, transform and atomically load one CSV file."""
    dataframe = read_csv(
        path,
        expected_columns=expected_columns,
        options=read_options,
    )
    dataframe = transform(dataframe)
    if not isinstance(dataframe, pd.DataFrame):
        raise TypeError("Pipeline transform must return a pandas DataFrame")

    source_filename = path.name
    batch_id = uuid4()
    engine: Engine = get_engine()

    with engine.begin() as connection:
        connection.execute(
            text("DELETE FROM bronze.import_batches WHERE source_filename = :source_filename"),
            {"source_filename": source_filename},
        )
        connection.execute(
            text(
                """
                INSERT INTO bronze.import_batches (id, source_filename, source_sha256, row_count)
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

        rows_to_load = dataframe.copy()
        rows_to_load.insert(0, "batch_id", batch_id)
        load_types = {"batch_id": PostgreSQLUUID(as_uuid=True), **(column_types or {})}
        load_dataframe(
            connection,
            rows_to_load,
            schema=schema,
            table=table,
            column_types=load_types,
        )

    return ImportResult(
        batch_id=batch_id,
        source_filename=source_filename,
        row_count=len(dataframe),
    )
