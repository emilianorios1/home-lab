from sqlalchemy import create_engine, text

from home_lab.gmail.repository import GmailRepository


def test_deduplicates_rotated_attachment_id_by_message_and_content() -> None:
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text("ATTACH DATABASE ':memory:' AS bronze"))
        connection.execute(
            text(
                """
                CREATE TABLE bronze.gmail_attachments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    message_id TEXT NOT NULL,
                    attachment_id TEXT NOT NULL,
                    original_filename TEXT NOT NULL,
                    mime_type TEXT NOT NULL,
                    byte_size INTEGER NOT NULL,
                    sha256 TEXT NOT NULL,
                    storage_path TEXT NOT NULL,
                    UNIQUE (message_id, attachment_id)
                )
                """
            )
        )

    repository = GmailRepository(engine)
    attachment = {
        "message_id": "message-1",
        "attachment_id": "attachment-1",
        "original_filename": "invoice.pdf",
        "mime_type": "application/pdf",
        "byte_size": 10,
        "sha256": "same-content",
        "storage_path": "invoice.pdf",
    }

    assert repository.save_attachment(attachment)
    assert not repository.save_attachment(
        {**attachment, "attachment_id": "rotated-attachment-id"}
    )
    assert repository.save_attachment(
        {
            **attachment,
            "message_id": "message-2",
            "attachment_id": "attachment-2",
        }
    )

    with engine.connect() as connection:
        rows = connection.execute(
            text(
                """
                SELECT message_id, sha256
                FROM bronze.gmail_attachments
                ORDER BY message_id
                """
            )
        ).all()

    assert rows == [
        ("message-1", "same-content"),
        ("message-2", "same-content"),
    ]
