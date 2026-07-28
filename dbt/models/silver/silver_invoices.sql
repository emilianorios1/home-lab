{{ config(schema='silver', alias='invoices') }}

select
    document_id as invoice_id,
    document_id,
    extracted_data ->> 'document_type' as document_type,
    extracted_data ->> 'issuer' as issuer,
    extracted_data ->> 'unit' as unit,
    (extracted_data ->> 'period')::date as period,
    (extracted_data ->> 'issue_date')::date as issue_date,
    (extracted_data ->> 'first_due_date')::date as first_due_date,
    (extracted_data ->> 'first_due_amount')::numeric(18, 2) as first_due_amount,
    (extracted_data ->> 'second_due_date')::date as second_due_date,
    (extracted_data ->> 'second_due_amount')::numeric(18, 2) as second_due_amount,
    coalesce(extracted_data ->> 'due_date_kind', 'alternative') as due_date_kind,
    nullif(extracted_data ->> 'total_amount', '')::numeric(18, 2) as total_amount,
    nullif(extracted_data ->> 'previous_balance', '')::numeric(18, 2) as previous_balance,
    nullif(extracted_data ->> 'collections', '')::numeric(18, 2) as collections
from {{ ref('silver_documents') }}
where parse_status = 'parsed'
  and extracted_data ->> 'document_type' in (
      'condominium_expense',
      'electricity_bill',
      'water_bill',
      'gas_bill'
  )
