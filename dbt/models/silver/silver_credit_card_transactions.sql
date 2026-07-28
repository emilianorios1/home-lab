{{ config(schema='silver', alias='credit_card_transactions') }}

select
    d.document_id as statement_id,
    transaction.ordinality::integer as line_number,
    (transaction.value ->> 'purchase_date')::date as purchase_date,
    transaction.value ->> 'card' as card,
    transaction.value ->> 'coupon' as coupon,
    transaction.value ->> 'description' as description,
    transaction.value ->> 'installment' as installment,
    transaction.value ->> 'currency' as currency,
    (transaction.value ->> 'amount')::numeric(18, 2) as amount,
    transaction.value ->> 'kind' as transaction_kind
from {{ ref('silver_documents') }} d
cross join lateral jsonb_array_elements(
    coalesce(d.extracted_data -> 'transactions', '[]'::jsonb)
) with ordinality as transaction(value, ordinality)
where d.parse_status = 'parsed'
  and d.extracted_data ->> 'document_type' = 'credit_card_statement'
