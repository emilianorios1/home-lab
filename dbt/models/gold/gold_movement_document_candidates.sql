{{ config(schema='gold', alias='movement_document_candidates') }}

select
    m.source,
    m.source_movement_id,
    d.invoice_id,
    d.due_number,
    m.release_date as movement_date,
    d.due_date,
    m.amount as movement_amount,
    d.amount as invoice_amount,
    abs(m.release_date - d.due_date) as days_apart,
    case
        when m.release_date = d.due_date then 1.00
        when abs(m.release_date - d.due_date) <= 3 then 0.90
        else 0.75
    end::numeric(3, 2) as confidence
from {{ ref('silver_movements') }} m
join {{ ref('silver_invoice_due_dates') }} d
  on abs(m.amount) = d.amount
 and m.release_date between d.due_date - 7 and d.due_date + 14
where m.amount < 0
