{{ config(schema='silver', alias='invoice_due_dates') }}

select
    invoice_id,
    1 as due_number,
    first_due_date as due_date,
    first_due_amount as amount
from {{ ref('silver_invoices') }}

union all

select
    invoice_id,
    2 as due_number,
    second_due_date as due_date,
    second_due_amount as amount
from {{ ref('silver_invoices') }}
