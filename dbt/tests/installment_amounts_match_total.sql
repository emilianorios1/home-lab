select
    invoice_id,
    first_due_amount,
    second_due_amount,
    total_amount
from {{ ref('silver_invoices') }}
where due_date_kind = 'installment'
  and first_due_amount + second_due_amount <> total_amount
