"""Read-only queries used by the dashboard."""

from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

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


def shared_expense_months(engine: Engine) -> list[date]:
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                """
                SELECT DISTINCT summary_month
                FROM (
                    SELECT summary_month
                    FROM gold.shared_expense_items
                    UNION ALL
                    SELECT date_trunc('month', release_date)::date
                    FROM gold.movements
                    WHERE category = 'Alquiler'
                ) months
                WHERE summary_month IS NOT NULL
                ORDER BY summary_month
                """
            )
        )
    return [row.summary_month for row in rows]


def monthly_shared_expenses(engine: Engine, month: date) -> dict[str, object]:
    """Build the spreadsheet-style monthly household expense summary."""
    with engine.connect() as connection:
        bill_rows = connection.execute(
            text(
                """
                SELECT
                    category,
                    sum(expected_amount) AS expected_amount,
                    sum(coalesce(paid_amount, 0)) AS paid_amount,
                    count(*) AS bill_count,
                    count(*) FILTER (WHERE payment_status = 'paid') AS paid_count
                FROM gold.shared_expense_items
                WHERE summary_month = :month
                GROUP BY category
                """
            ),
            {"month": month},
        )
        bills = {row.category: row for row in bill_rows}
        rent_net = connection.execute(
            text(
                """
                SELECT coalesce(sum(abs(amount)), 0)
                FROM gold.movements
                WHERE category = 'Alquiler'
                  AND date_trunc('month', release_date)::date = :month
                """
            ),
            {"month": month},
        ).scalar_one()
        extraordinary = connection.execute(
            text(
                """
                SELECT coalesce(sum(items.amount), 0)
                FROM silver.invoice_line_items items
                JOIN silver.invoices invoices using (invoice_id)
                WHERE items.concept_code = 'extraordinary_expenses'
                  AND date_trunc('month', invoices.first_due_date)::date = :month
                """
            ),
            {"month": month},
        ).scalar_one()

    rent_net = Decimal(rent_net)
    extraordinary = Decimal(extraordinary)
    gross_rent = rent_net + extraordinary

    def bill_values(category: str) -> tuple[Decimal, Decimal, str]:
        bill = bills.get(category)
        if bill is None:
            return Decimal("0"), Decimal("0"), "Sin factura"
        expected = Decimal(bill.expected_amount)
        paid = Decimal(bill.paid_amount)
        if bill.paid_count == bill.bill_count:
            status = "Pagado"
        elif bill.paid_count:
            status = "Parcial"
        else:
            status = "Pendiente"
        return expected, paid, status

    rows: list[dict[str, object]] = [
        {
            "concept": "Alquiler bruto",
            "amount": gross_rent,
            "paid_amount": rent_net,
            "status": "Calculado" if rent_net else "Sin movimiento",
        },
        {
            "concept": "Expensas extraordinarias",
            "amount": extraordinary,
            "paid_amount": extraordinary if rent_net else Decimal("0"),
            "status": "Descontado" if extraordinary else "Sin factura",
        },
    ]
    expected_bills = Decimal("0")
    paid_bills = Decimal("0")
    for category, label in (
        ("Expensas", "Expensas a pagar"),
        ("Luz", "Luz"),
        ("Agua", "Agua"),
        ("Gas", "Gas"),
        ("TGI", "TGI"),
    ):
        expected, paid, status = bill_values(category)
        expected_bills += expected
        paid_bills += paid
        row = {
            "concept": label,
            "amount": expected,
            "paid_amount": paid,
            "status": status,
        }
        rows.append(row)
        if category == "Expensas":
            rows.append(
                {
                    "concept": "Alquiler a pagar",
                    "amount": rent_net,
                    "paid_amount": rent_net,
                    "status": "Pagado" if rent_net else "Sin movimiento",
                }
            )

    shared_total = rent_net + expected_bills
    paid_total = rent_net + paid_bills
    return {
        "month": month,
        "rows": pd.DataFrame(rows),
        "shared_total": shared_total,
        "per_person": (shared_total / Decimal("2")).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP,
        ),
        "paid_total": paid_total,
    }
