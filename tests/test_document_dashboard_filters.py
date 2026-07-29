from datetime import date

import pandas as pd
import pytest

from home_lab.dashboard.queries import documents


def test_documents_accepts_structured_filters(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def read_sql(statement: object, engine: object, params: object) -> pd.DataFrame:
        captured["statement"] = str(statement)
        captured["params"] = params
        return pd.DataFrame()

    monkeypatch.setattr("home_lab.dashboard.queries.pd.read_sql", read_sql)
    documents(
        object(),
        date(2026, 6, 1),
        date(2026, 6, 30),
        "factura",
        document_types=("gas_bill",),
        issuers=("Litoral Gas",),
        parse_statuses=("parsed",),
    )

    assert "document_type = ANY" in str(captured["statement"])
    assert captured["params"] == {
        "start_date": date(2026, 6, 1),
        "end_date": date(2026, 6, 30),
        "search": "factura",
        "search_pattern": "%factura%",
        "document_types": ["gas_bill"],
        "issuers": ["Litoral Gas"],
        "parse_statuses": ["parsed"],
        "limit": 200,
    }
