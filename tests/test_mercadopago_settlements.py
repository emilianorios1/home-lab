from pathlib import Path

import pandas as pd
import pytest

from pipelines.mercadopago_settlements import CSV_COLUMNS, file_sha256, normalize, read_csv


def sample_dataframe() -> pd.DataFrame:
    return pd.DataFrame(
        [["170599700130", "available_money", "SETTLEMENT", "-10.25", "2026-07-26T00:18:24.000-04:00", "0.00", "2026-07-26T00:18:24.000-04:00", "-10.25", "0.00", "Mercado Pago", "Checkouts", "2026-07-26T00:18:24.000-04:00"]],
        columns=CSV_COLUMNS,
    )


def test_normalize_preserves_raw_values_with_database_types() -> None:
    record = normalize(sample_dataframe())[0]
    assert str(record["transaction_amount"]) == "-10.25"
    assert record["transaction_date"].isoformat() == "2026-07-26T04:18:24+00:00"
    assert record["business_unit"] == "Mercado Pago"


def test_read_csv_rejects_wrong_columns(tmp_path: Path) -> None:
    path = tmp_path / "bad.csv"
    path.write_text("WRONG\nvalue\n")
    with pytest.raises(ValueError, match="Unexpected Mercado Pago CSV columns"):
        read_csv(path)


def test_file_sha256_is_stable(tmp_path: Path) -> None:
    path = tmp_path / "report.csv"
    path.write_text("report")
    assert file_sha256(path) == file_sha256(path)
