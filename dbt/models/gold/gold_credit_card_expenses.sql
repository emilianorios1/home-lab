{{ config(schema='gold', alias='credit_card_expenses') }}

select
    transactions.statement_id,
    transactions.line_number,
    invoices.period as statement_period,
    invoices.first_due_date as statement_due_date,
    invoices.issuer,
    transactions.purchase_date,
    transactions.card,
    transactions.coupon,
    transactions.description,
    transactions.installment,
    transactions.currency,
    transactions.amount,
    transactions.transaction_kind,
    case
        when transactions.transaction_kind = 'interest' then 'Intereses'
        when transactions.transaction_kind = 'fee' then 'Comisiones'
        when transactions.transaction_kind = 'tax' then 'Impuestos'
        when transactions.description ilike '%SEGURO%'
          or transactions.description ilike '%GALICIA SEG%' then 'Seguros'
        when transactions.description ilike '%AXION%'
          or transactions.description ilike '%YPF%'
          or transactions.description ilike '%SHELL%' then 'Combustible'
        when transactions.description ilike '%CLARO%'
          or transactions.description ilike '%PERSONAL%'
          or transactions.description ilike '%MOVISTAR%' then 'Telefonía'
        when transactions.description ilike '%UNIV%'
          or transactions.description ilike '%EDUC%' then 'Educación'
        when transactions.description ilike '%OPENAI%'
          or transactions.description ilike '%CHATGPT%' then 'Software'
        else 'Sin categorizar'
    end as category
from {{ ref('silver_credit_card_transactions') }} transactions
join {{ ref('silver_invoices') }} invoices
  on invoices.invoice_id = transactions.statement_id
