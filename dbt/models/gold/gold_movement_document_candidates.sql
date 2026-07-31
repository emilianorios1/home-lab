{{ config(schema='gold', alias='movement_document_candidates') }}

with invoice_dues as (
    select
        d.*,
        i.document_type,
        case i.document_type
            when 'condominium_expense' then 'Expensas'
            when 'electricity_bill' then 'Luz'
            when 'water_bill' then 'Agua'
            when 'gas_bill' then 'Gas'
            when 'property_tax_bill' then 'TGI'
            when 'internet_bill' then 'Internet'
            when 'credit_card_statement' then 'Tarjeta Naranja'
        end as bill_category
    from {{ ref('silver_invoice_due_dates') }} d
    join {{ ref('silver_invoices') }} i using (invoice_id)
),

raw_candidates as (
    select
        m.source,
        m.source_movement_id,
        d.invoice_id,
        d.due_number,
        m.release_date as movement_date,
        d.due_date,
        m.amount as movement_amount,
        d.amount as invoice_amount,
        m.category as movement_category,
        d.bill_category,
        abs(abs(m.amount) - d.amount) as amount_difference,
        abs(m.release_date - d.due_date) as days_apart,
        m.category = d.bill_category as category_matches
    from {{ ref('silver_movements') }} m
    join invoice_dues d
      on (
        (
            m.category = d.bill_category
            and abs(abs(m.amount) - d.amount) <= greatest(1, d.amount * 0.01)
        )
        or (
            m.category = 'Sin categorizar'
            and abs(abs(m.amount) - d.amount) <= 1
        )
     )
     and m.release_date between d.due_date - 45 and d.due_date + 45
    where m.amount < 0
),

ranked as (
    select
        *,
        row_number() over (
            partition by source, source_movement_id
            order by
                category_matches desc,
                amount_difference,
                days_apart,
                invoice_id,
                due_number
        ) as candidate_rank
    from raw_candidates
)

select
    source,
    source_movement_id,
    invoice_id,
    due_number,
    movement_date,
    due_date,
    movement_amount,
    invoice_amount,
    movement_category,
    bill_category,
    amount_difference,
    days_apart,
    candidate_rank,
    greatest(
        0.50,
        1.00
        - least(amount_difference / nullif(invoice_amount, 0), 0.10)
        - least(days_apart::numeric / 300, 0.15)
        + case when category_matches then 0.05 else 0 end
    )::numeric(4, 2) as confidence
from ranked
