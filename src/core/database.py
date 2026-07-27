"""PostgreSQL schema and connection helpers."""

from __future__ import annotations

from sqlalchemy import Engine, create_engine, text

from core.config import database_url


def get_engine() -> Engine:
    return create_engine(database_url())


def create_schema(engine: Engine) -> None:
    statements = [
        "CREATE SCHEMA IF NOT EXISTS raw",
        """
        CREATE TABLE IF NOT EXISTS raw.import_batches (
            id UUID PRIMARY KEY,
            source_filename TEXT NOT NULL UNIQUE,
            source_sha256 TEXT NOT NULL,
            imported_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            row_count INTEGER NOT NULL CHECK (row_count >= 0)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS raw.mercadopago_settlements (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            batch_id UUID NOT NULL REFERENCES raw.import_batches(id) ON DELETE CASCADE,
            source_id TEXT,
            payment_method_type TEXT,
            transaction_type TEXT,
            transaction_amount NUMERIC(18, 2),
            transaction_date TIMESTAMPTZ,
            fee_amount NUMERIC(18, 2),
            settlement_date TIMESTAMPTZ,
            real_amount NUMERIC(18, 2),
            taxes_amount NUMERIC(18, 2),
            business_unit TEXT,
            sub_unit TEXT,
            money_release_date TIMESTAMPTZ
        )
        """,
        "CREATE INDEX IF NOT EXISTS mercadopago_settlements_batch_id_idx ON raw.mercadopago_settlements(batch_id)",
    ]
    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))
