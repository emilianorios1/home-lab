{{ config(schema='gold', alias='bill_payments') }}

with best_for_movement as (
    select *
    from {{ ref('gold_movement_document_candidates') }}
    where candidate_rank = 1
),

best_for_bill as (
    select
        *,
        row_number() over (
            partition by invoice_id, due_number
            order by
                confidence desc,
                amount_difference,
                days_apart,
                movement_date,
                source_movement_id
        ) as bill_rank
    from best_for_movement
)

select
    source,
    source_movement_id,
    invoice_id,
    due_number,
    movement_date as payment_date,
    due_date,
    abs(movement_amount) as paid_amount,
    invoice_amount,
    confidence
from best_for_bill
where bill_rank = 1
