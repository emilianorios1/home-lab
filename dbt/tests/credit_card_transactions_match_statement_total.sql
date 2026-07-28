with transaction_totals as (
    select
        statement_id,
        sum(amount) as amount
    from {{ ref('silver_credit_card_transactions') }}
    where currency = 'ARS'
    group by statement_id
)

select
    invoices.invoice_id,
    invoices.total_amount,
    transaction_totals.amount
from {{ ref('silver_invoices') }} invoices
join transaction_totals
  on transaction_totals.statement_id = invoices.invoice_id
where invoices.document_type = 'credit_card_statement'
  and invoices.total_amount <> transaction_totals.amount
