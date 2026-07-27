"""Read-only queries used by the dashboard."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pandas as pd
from sqlalchemy import Engine, text


def available_date_range(engine: Engine) -> tuple[date, date] | None:
    with engine.connect() as connection:
        row = connection.execute(
            text(
                """
                WITH dates AS (
                    SELECT release_date AS value FROM gold.movements
                    UNION ALL
                    SELECT coalesce(issue_date, received_at::date) AS value
                    FROM gold.documents
                )
                SELECT min(value) AS start_date, max(value) AS end_date
                FROM dates
                """
            )
        ).one()
    if row.start_date is None:
        return None
    return row.start_date, row.end_date


def overview(engine: Engine, start_date: date, end_date: date) -> dict[str, Decimal]:
    with engine.connect() as connection:
        row = connection.execute(
            text(
                """
                SELECT
                    coalesce(sum(amount) FILTER (WHERE amount > 0), 0) AS income,
                    coalesce(sum(amount) FILTER (WHERE amount < 0), 0) AS expenses,
                    coalesce(sum(amount), 0) AS net_flow,
                    coalesce((
                        SELECT running_balance
                        FROM gold.movements
                        WHERE release_date BETWEEN :start_date AND :end_date
                        ORDER BY release_date DESC, source_movement_id DESC
                        LIMIT 1
                    ), 0) AS closing_balance
                FROM gold.movements
                WHERE release_date BETWEEN :start_date AND :end_date
                """
            ),
            {"start_date": start_date, "end_date": end_date},
        ).one()
    return dict(row._mapping)


def daily_flow(engine: Engine, start_date: date, end_date: date) -> pd.DataFrame:
    return pd.read_sql(
        text(
            """
            SELECT
                release_date,
                coalesce(sum(amount) FILTER (WHERE amount > 0), 0) AS income,
                coalesce(sum(amount) FILTER (WHERE amount < 0), 0) AS expenses
            FROM gold.movements
            WHERE release_date BETWEEN :start_date AND :end_date
            GROUP BY release_date
            ORDER BY release_date
            """
        ),
        engine,
        params={"start_date": start_date, "end_date": end_date},
    )


def daily_balance(engine: Engine, start_date: date, end_date: date) -> pd.DataFrame:
    return pd.read_sql(
        text(
            """
            SELECT DISTINCT ON (release_date) release_date, running_balance AS partial_balance
            FROM gold.movements
            WHERE release_date BETWEEN :start_date AND :end_date
            ORDER BY release_date, source_movement_id DESC
            """
        ),
        engine,
        params={"start_date": start_date, "end_date": end_date},
    )


def expenses_by_category(engine: Engine, start_date: date, end_date: date) -> pd.DataFrame:
    return pd.read_sql(
        text(
            """
            SELECT category, sum(amount) AS amount
            FROM gold.movements
            WHERE release_date BETWEEN :start_date AND :end_date
              AND amount < 0
            GROUP BY category
            ORDER BY amount
            """
        ),
        engine,
        params={"start_date": start_date, "end_date": end_date},
    )


def movements(
    engine: Engine,
    start_date: date,
    end_date: date,
    search: str = "",
    limit: int = 500,
) -> pd.DataFrame:
    return pd.read_sql(
        text(
            """
            SELECT
                release_date,
                description AS transaction_type,
                reference_id,
                category,
                amount AS transaction_net_amount,
                running_balance AS partial_balance,
                source
            FROM gold.movements
            WHERE release_date BETWEEN :start_date AND :end_date
              AND (:search = '' OR description ILIKE :search_pattern)
            ORDER BY release_date DESC, source_movement_id DESC
            LIMIT :limit
            """
        ),
        engine,
        params={
            "start_date": start_date,
            "end_date": end_date,
            "search": search.strip(),
            "search_pattern": f"%{search.strip()}%",
            "limit": limit,
        },
    )


def documents(
    engine: Engine,
    start_date: date,
    end_date: date,
    search: str = "",
    limit: int = 200,
) -> pd.DataFrame:
    return pd.read_sql(
        text(
            """
            SELECT
                document_id,
                coalesce(issue_date, received_at::date) AS document_date,
                period,
                issuer,
                unit,
                first_due_date,
                first_due_amount,
                second_due_date,
                second_due_amount,
                parse_status,
                original_filename,
                storage_path,
                byte_size,
                error_message
            FROM gold.documents
            WHERE coalesce(issue_date, received_at::date)
                  BETWEEN :start_date AND :end_date
              AND (
                  :search = ''
                  OR coalesce(issuer, '') ILIKE :search_pattern
                  OR coalesce(original_filename, '') ILIKE :search_pattern
                  OR coalesce(unit, '') ILIKE :search_pattern
              )
            ORDER BY coalesce(issue_date, received_at::date) DESC, document_id DESC
            LIMIT :limit
            """
        ),
        engine,
        params={
            "start_date": start_date,
            "end_date": end_date,
            "search": search.strip(),
            "search_pattern": f"%{search.strip()}%",
            "limit": limit,
        },
    )
