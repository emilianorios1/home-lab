"""Manual monthly rent persistence."""

from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import Engine, text


def calculate_net_rent(gross_amount: Decimal, extraordinary: Decimal) -> Decimal:
    return max(gross_amount - extraordinary, Decimal("0"))


def save_monthly_rent(engine: Engine, month: date, gross_amount: Decimal) -> Decimal:
    amount = gross_amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if amount <= 0:
        raise ValueError("gross_amount must be positive")

    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO bronze.manual_monthly_rents (
                    summary_month,
                    gross_amount
                )
                VALUES (:month, :gross_amount)
                ON CONFLICT (summary_month) DO UPDATE
                SET gross_amount = excluded.gross_amount,
                    updated_at = now()
                """
            ),
            {
                "month": month.replace(day=1),
                "gross_amount": amount,
            },
        )
    return amount
