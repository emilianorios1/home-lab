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
    due_date_kind,
    total_amount,
    foreign_total_amount,
    foreign_currency,
    minimum_payment,
    case
        when due_date_kind = 'installment'
            then coalesce(total_amount, first_due_amount + second_due_amount)
        when due_date_kind = 'single' then first_due_amount
        when current_date <= first_due_date then first_due_amount
        else second_due_amount
    end as current_amount,
    case
        when current_date > coalesce(second_due_date, first_due_date) then 'overdue'
        else 'pending'
    end as status
from {{ ref('silver_invoices') }}
