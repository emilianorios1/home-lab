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
                SELECT min(release_date) AS start_date, max(release_date) AS end_date
                FROM analytics.mercadopago_movements
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
                    coalesce(sum(transaction_net_amount) FILTER (WHERE transaction_net_amount > 0), 0) AS income,
                    coalesce(sum(transaction_net_amount) FILTER (WHERE transaction_net_amount < 0), 0) AS expenses,
                    coalesce(sum(transaction_net_amount), 0) AS net_flow,
                    coalesce((
                        SELECT partial_balance
                        FROM analytics.mercadopago_movements
                        WHERE release_date BETWEEN :start_date AND :end_date
                        ORDER BY release_date DESC, id DESC
                        LIMIT 1
                    ), 0) AS closing_balance
                FROM analytics.mercadopago_movements
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
                coalesce(sum(transaction_net_amount) FILTER (WHERE transaction_net_amount > 0), 0) AS income,
                coalesce(sum(transaction_net_amount) FILTER (WHERE transaction_net_amount < 0), 0) AS expenses
            FROM analytics.mercadopago_movements
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
            SELECT DISTINCT ON (release_date) release_date, partial_balance
            FROM analytics.mercadopago_movements
            WHERE release_date BETWEEN :start_date AND :end_date
            ORDER BY release_date, id DESC
            """
        ),
        engine,
        params={"start_date": start_date, "end_date": end_date},
    )


def expenses_by_category(engine: Engine, start_date: date, end_date: date) -> pd.DataFrame:
    return pd.read_sql(
        text(
            """
            SELECT category, sum(transaction_net_amount) AS amount
            FROM analytics.mercadopago_movements
            WHERE release_date BETWEEN :start_date AND :end_date
              AND transaction_net_amount < 0
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
                transaction_type,
                reference_id,
                category,
                transaction_net_amount,
                partial_balance
            FROM analytics.mercadopago_movements
            WHERE release_date BETWEEN :start_date AND :end_date
              AND (:search = '' OR transaction_type ILIKE :search_pattern)
            ORDER BY release_date DESC, id DESC
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
