"""PostgreSQL schema and connection helpers."""

from __future__ import annotations

from sqlalchemy import Engine, create_engine, text

from home_lab.config import database_url


def get_engine() -> Engine:
    return create_engine(database_url())


def create_schema(engine: Engine) -> None:
    statements = [
        "CREATE SCHEMA IF NOT EXISTS bronze",
        "CREATE SCHEMA IF NOT EXISTS silver",
        "CREATE SCHEMA IF NOT EXISTS gold",
        # Legacy raw tables remain readable while existing installations migrate.
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
        CREATE TABLE IF NOT EXISTS raw.mercadopago_account_statements (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            batch_id UUID NOT NULL REFERENCES raw.import_batches(id) ON DELETE CASCADE,
            release_date DATE,
            transaction_type TEXT,
            reference_id TEXT,
            transaction_net_amount NUMERIC(18, 2),
            partial_balance NUMERIC(18, 2)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS bronze.import_batches (
            id UUID PRIMARY KEY,
            source_filename TEXT NOT NULL UNIQUE,
            source_sha256 TEXT NOT NULL,
            imported_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            row_count INTEGER NOT NULL CHECK (row_count >= 0)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS bronze.mercadopago_account_statements (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            batch_id UUID NOT NULL REFERENCES bronze.import_batches(id) ON DELETE CASCADE,
            release_date DATE,
            transaction_type TEXT,
            reference_id TEXT,
            transaction_net_amount NUMERIC(18, 2),
            partial_balance NUMERIC(18, 2)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS bronze.financial_statements (
            id UUID PRIMARY KEY,
            provider TEXT NOT NULL,
            account_key TEXT NOT NULL,
            statement_type TEXT NOT NULL,
            period_start DATE NOT NULL,
            period_end DATE NOT NULL,
            source_filename TEXT NOT NULL,
            source_format TEXT NOT NULL,
            source_sha256 TEXT NOT NULL,
            storage_path TEXT NOT NULL,
            byte_size BIGINT NOT NULL CHECK (byte_size >= 0),
            initial_balance NUMERIC(18, 2) NOT NULL,
            credits NUMERIC(18, 2) NOT NULL,
            debits NUMERIC(18, 2) NOT NULL,
            final_balance NUMERIC(18, 2) NOT NULL,
            row_count INTEGER NOT NULL CHECK (row_count >= 0),
            imported_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CHECK (period_end >= period_start),
            UNIQUE (
                provider, account_key, statement_type, period_start, period_end
            ),
            UNIQUE (provider, account_key, source_sha256)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS bronze.mercadopago_statement_movements (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            statement_id UUID NOT NULL
                REFERENCES bronze.financial_statements(id) ON DELETE CASCADE,
            line_number INTEGER NOT NULL CHECK (line_number > 0),
            release_date DATE NOT NULL,
            transaction_type TEXT,
            reference_id TEXT,
            transaction_net_amount NUMERIC(18, 2) NOT NULL,
            partial_balance NUMERIC(18, 2) NOT NULL,
            UNIQUE (statement_id, line_number)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS bronze.mercadopago_api_movements (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            batch_id UUID NOT NULL
                REFERENCES bronze.import_batches(id) ON DELETE CASCADE,
            release_date DATE,
            transaction_type TEXT,
            reference_id TEXT,
            transaction_net_amount NUMERIC(18, 2),
            partial_balance NUMERIC(18, 2)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS bronze.ingestion_runs (
            id UUID PRIMARY KEY,
            source TEXT NOT NULL,
            query TEXT,
            status TEXT NOT NULL CHECK (status IN ('running', 'succeeded', 'failed')),
            started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            completed_at TIMESTAMPTZ,
            records_discovered INTEGER NOT NULL DEFAULT 0,
            records_loaded INTEGER NOT NULL DEFAULT 0,
            error_message TEXT
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS bronze.gmail_messages (
            message_id TEXT PRIMARY KEY,
            thread_id TEXT,
            history_id TEXT,
            internal_date TIMESTAMPTZ,
            sender TEXT,
            subject TEXT,
            received_at TIMESTAMPTZ,
            snippet TEXT,
            metadata_path TEXT NOT NULL,
            ingestion_run_id UUID REFERENCES bronze.ingestion_runs(id),
            ingested_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS bronze.gmail_attachments (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            message_id TEXT NOT NULL REFERENCES bronze.gmail_messages(message_id),
            attachment_id TEXT NOT NULL,
            original_filename TEXT NOT NULL,
            mime_type TEXT NOT NULL,
            byte_size BIGINT NOT NULL CHECK (byte_size >= 0),
            sha256 TEXT NOT NULL,
            storage_path TEXT NOT NULL,
            ingested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (message_id, attachment_id)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS bronze.document_parse_results (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            attachment_id BIGINT NOT NULL REFERENCES bronze.gmail_attachments(id),
            parser_name TEXT NOT NULL,
            parser_version TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('parsed', 'unsupported', 'failed')),
            page_count INTEGER,
            extracted_text TEXT,
            extracted_data JSONB,
            error_message TEXT,
            parsed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (attachment_id, parser_name, parser_version)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS bronze.manual_shared_expenses (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            summary_month DATE NOT NULL,
            category TEXT NOT NULL CHECK (
                category IN ('Expensas', 'Luz', 'Agua', 'Gas', 'TGI')
            ),
            issuer TEXT NOT NULL,
            due_date DATE,
            expected_amount NUMERIC(18, 2) NOT NULL
                CHECK (expected_amount >= 0),
            payment_date DATE,
            paid_amount NUMERIC(18, 2)
                CHECK (paid_amount IS NULL OR paid_amount >= 0),
            payment_status TEXT NOT NULL
                CHECK (payment_status IN ('pending', 'paid')),
            source TEXT NOT NULL,
            source_reference TEXT,
            notes TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (summary_month, category, issuer)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS bronze.manual_monthly_rents (
            summary_month DATE PRIMARY KEY
                CHECK (extract(day FROM summary_month) = 1),
            gross_amount NUMERIC(18, 2) NOT NULL CHECK (gross_amount > 0),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS bronze.export_invoice_emissions (
            request_id BIGINT PRIMARY KEY,
            environment TEXT NOT NULL CHECK (environment = 'dev'),
            tax_id BIGINT NOT NULL,
            status TEXT NOT NULL CHECK (
                status IN ('pending', 'authorized', 'rejected', 'unknown')
            ),
            point_of_sale INTEGER NOT NULL CHECK (point_of_sale > 0),
            voucher_type SMALLINT NOT NULL CHECK (voucher_type = 19),
            voucher_number BIGINT,
            issue_date DATE NOT NULL,
            payment_date DATE NOT NULL CHECK (payment_date >= issue_date),
            client_name TEXT NOT NULL,
            client_address TEXT NOT NULL,
            foreign_tax_id TEXT NOT NULL,
            destination_country_code INTEGER NOT NULL,
            destination_country_tax_id BIGINT NOT NULL,
            description TEXT NOT NULL,
            unit_code INTEGER NOT NULL,
            foreign_currency TEXT NOT NULL CHECK (foreign_currency = 'USD'),
            foreign_total_amount NUMERIC(18, 2) NOT NULL
                CHECK (foreign_total_amount > 0),
            exchange_rate NUMERIC(18, 6) NOT NULL CHECK (exchange_rate > 0),
            request_payload JSONB,
            response_payload JSONB,
            cae TEXT UNIQUE,
            cae_due_date DATE,
            error_code TEXT,
            error_message TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
        """
        ALTER TABLE bronze.export_invoice_emissions
        DROP CONSTRAINT IF EXISTS
            export_invoice_emissions_environment_point_of_sale_voucher_type_voucher_number_key
        """,
        """
        ALTER TABLE bronze.export_invoice_emissions
        DROP CONSTRAINT IF EXISTS
            export_invoice_emissions_environment_point_of_sale_voucher__key
        """,
        """
        CREATE TABLE IF NOT EXISTS bronze.recurring_export_invoice_profile (
            id SMALLINT PRIMARY KEY CHECK (id = 1),
            point_of_sale INTEGER NOT NULL CHECK (point_of_sale > 0),
            client_name TEXT NOT NULL,
            client_address TEXT NOT NULL,
            foreign_tax_id TEXT NOT NULL,
            destination_country_code INTEGER NOT NULL,
            destination_country_tax_id BIGINT NOT NULL,
            description TEXT NOT NULL,
            unit_code INTEGER NOT NULL,
            amount_usd NUMERIC(18, 2) NOT NULL CHECK (amount_usd > 0),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
        "CREATE INDEX IF NOT EXISTS mercadopago_account_statements_batch_id_idx ON raw.mercadopago_account_statements(batch_id)",
        "CREATE INDEX IF NOT EXISTS bronze_mercadopago_batch_id_idx ON bronze.mercadopago_account_statements(batch_id)",
        "CREATE INDEX IF NOT EXISTS financial_statements_coverage_idx ON bronze.financial_statements(provider, account_key, period_start, period_end)",
        "CREATE INDEX IF NOT EXISTS mercadopago_statement_movements_statement_idx ON bronze.mercadopago_statement_movements(statement_id)",
        "CREATE INDEX IF NOT EXISTS mercadopago_api_movements_batch_idx ON bronze.mercadopago_api_movements(batch_id)",
        "CREATE INDEX IF NOT EXISTS gmail_attachments_sha256_idx ON bronze.gmail_attachments(sha256)",
        "CREATE INDEX IF NOT EXISTS document_parse_status_idx ON bronze.document_parse_results(status)",
        "CREATE INDEX IF NOT EXISTS manual_shared_expenses_month_idx ON bronze.manual_shared_expenses(summary_month)",
        "CREATE INDEX IF NOT EXISTS export_invoice_emissions_status_idx ON bronze.export_invoice_emissions(status)",
        """
        CREATE UNIQUE INDEX IF NOT EXISTS export_invoice_emissions_active_voucher_idx
        ON bronze.export_invoice_emissions (
            environment, point_of_sale, voucher_type, voucher_number
        )
        WHERE status <> 'rejected'
        """,
        """
        INSERT INTO bronze.import_batches
            (id, source_filename, source_sha256, imported_at, row_count)
        SELECT id, source_filename, source_sha256, imported_at, row_count
        FROM raw.import_batches
        ON CONFLICT DO NOTHING
        """,
        """
        INSERT INTO bronze.mercadopago_account_statements
            (batch_id, release_date, transaction_type, reference_id,
             transaction_net_amount, partial_balance)
        SELECT r.batch_id, r.release_date, r.transaction_type, r.reference_id,
               r.transaction_net_amount, r.partial_balance
        FROM raw.mercadopago_account_statements r
        JOIN bronze.import_batches b ON b.id = r.batch_id
        WHERE NOT EXISTS (
            SELECT 1
            FROM bronze.mercadopago_account_statements existing
            WHERE existing.batch_id = r.batch_id
              AND existing.release_date IS NOT DISTINCT FROM r.release_date
              AND existing.transaction_type IS NOT DISTINCT FROM r.transaction_type
              AND existing.reference_id IS NOT DISTINCT FROM r.reference_id
              AND existing.transaction_net_amount IS NOT DISTINCT FROM r.transaction_net_amount
              AND existing.partial_balance IS NOT DISTINCT FROM r.partial_balance
        )
        """,
    ]
    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))
