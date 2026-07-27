{{ config(schema='gold', alias='bills') }}

select
    invoice_id as bill_id,
    document_id,
    document_type,
    issuer,
    unit,
    period,
    issue_date,
    first_due_date,
    first_due_amount,
    second_due_date,
    second_due_amount,
    case
        when current_date <= first_due_date then first_due_amount
        else second_due_amount
    end as current_amount,
    case
        when current_date > second_due_date then 'overdue'
        else 'pending'
    end as status
from {{ ref('silver_invoices') }}
