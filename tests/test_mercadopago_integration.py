from pathlib import Path

from sqlalchemy import text

from core.database import get_engine
from pipelines.mercadopago_settlements import CSV_COLUMNS, import_csv


def test_import_replaces_a_batch_with_the_same_filename(tmp_path: Path) -> None:
    source = tmp_path / "integration-settlements.csv"
    source.write_text(
        ",".join(CSV_COLUMNS)
        + "\n"
        + "1,available_money,SETTLEMENT,-10.25,2026-07-26T00:18:24.000-04:00,0.00,2026-07-26T00:18:24.000-04:00,-10.25,0.00,Mercado Pago,Checkouts,2026-07-26T00:18:24.000-04:00\n"
    )
    engine = get_engine()

    try:
        first = import_csv(engine, source)
        second = import_csv(engine, source)

        assert first.batch_id != second.batch_id
        with engine.connect() as connection:
            batch_count = connection.execute(
                text("SELECT count(*) FROM raw.import_batches WHERE source_filename = :filename"),
                {"filename": source.name},
            ).scalar_one()
            row_count = connection.execute(
                text(
                    """
                    SELECT count(*)
                    FROM raw.mercadopago_settlements settlements
                    JOIN raw.import_batches batches ON batches.id = settlements.batch_id
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
                text("DELETE FROM raw.import_batches WHERE source_filename = :filename"),
                {"filename": source.name},
            )
