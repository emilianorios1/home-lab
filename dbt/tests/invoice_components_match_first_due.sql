with component_totals as (
    select
        invoice_id,
        sum(amount) as component_amount
    from {{ ref('silver_invoice_line_items') }}
    group by invoice_id
)

select
    invoices.invoice_id,
    invoices.first_due_amount,
    component_totals.component_amount
from {{ ref('silver_invoices') }} invoices
join component_totals using (invoice_id)
where invoices.first_due_amount <> component_totals.component_amount
