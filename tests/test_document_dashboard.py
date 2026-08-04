from datetime import date
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from pypdf import PdfWriter
from streamlit.testing.v1 import AppTest


def test_selecting_a_document_updates_preview_and_download(tmp_path: Path) -> None:
    pdf_path = tmp_path / "document.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    writer.write(pdf_path)

    common = {
        "period": date(2026, 8, 1),
        "unit": None,
        "first_due_date": date(2026, 8, 10),
        "first_due_amount": 100,
        "second_due_date": None,
        "second_due_amount": None,
        "parse_status": "parsed",
        "byte_size": 4,
        "error_message": None,
    }
    data = pd.DataFrame(
        [
            common
            | {
                "document_id": 1,
                "document_date": date(2026, 8, 1),
                "issuer": "Emisor A",
                "document_type": "gas_bill",
                "original_filename": "primero.pdf",
                "storage_path": "one.pdf",
            },
            common
            | {
                "document_id": 2,
                "document_date": date(2026, 8, 2),
                "issuer": "Emisor B",
                "document_type": "water_bill",
                "original_filename": "segundo.pdf",
                "storage_path": "two.pdf",
            },
        ]
    )
    options = data[["document_type"]]

    with (
        patch("home_lab.database.get_engine", return_value=object()),
        patch(
            "home_lab.dashboard.queries.document_filter_options",
            return_value=options,
        ),
        patch("home_lab.dashboard.queries.documents", return_value=data),
        patch("home_lab.config.document_store_path", return_value=Path("/tmp")),
        patch(
            "home_lab.documents.storage.resolve_document_path",
            return_value=pdf_path,
        ),
    ):
        app = AppTest.from_file("src/home_lab/dashboard/pages/documents.py")
        app.session_state["start_date"] = date(2026, 8, 1)
        app.session_state["end_date"] = date(2026, 8, 31)
        app.run(timeout=30)

        assert not app.exception
        assert len(app.dataframe) == 1
        assert [item.label for item in app.multiselect] == ["Tipo"]
        assert not app.selectbox
        assert [caption.value for caption in app.caption] == ["primero.pdf"]
        assert len(app.get("download_button")) == 1

        app.session_state["documents"] = {"selection": {"rows": [1]}}
        app.run(timeout=30)

        assert not app.exception
        assert [caption.value for caption in app.caption] == ["segundo.pdf"]
