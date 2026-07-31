{{ config(schema='silver', alias='invoices') }}

with iplan_candidates as (
    select
        message_id,
        received_at,
        substring(subject from '([0-9]{2}/[0-9]{4})') as period_text,
        substring(
            lower(snippet)
            from 'valor de tus servicios este mes es \$[[:space:]]*([0-9][0-9.,]*)'
        ) as amount_text,
        substring(
            lower(snippet)
            from '1er vencimiento es el ([0-9]{2}/[0-9]{2}/[0-9]{4})'
        ) as due_date_text
    from {{ source('bronze', 'gmail_messages') }}
    where lower(sender) like '%noreply@iplan.com.ar%'
      and lower(subject) like 'tu factura de iplan%hogar %/%'
),

iplan_invoices as (
    select
        -(
            ('x' || substr(md5('iplan:' || message_id), 1, 15))
                ::bit(60)::bigint
            + 1
        ) as invoice_id,
        message_id,
        to_date(period_text, 'MM/YYYY') as period,
        received_at::date as issue_date,
        to_date(due_date_text, 'DD/MM/YYYY') as first_due_date,
        (
            case
                when position(',' in amount_text) > 0
                    then replace(replace(amount_text, '.', ''), ',', '.')
                else amount_text
            end
        )::numeric(18, 2) as first_due_amount
    from iplan_candidates
    where period_text is not null
      and amount_text is not null
      and due_date_text is not null
)

select
    document_id as invoice_id,
    document_id,
    message_id as source_message_id,
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
    nullif(extracted_data ->> 'foreign_total_amount', '')::numeric(18, 2)
        as foreign_total_amount,
    extracted_data ->> 'foreign_currency' as foreign_currency,
    nullif(extracted_data ->> 'minimum_payment', '')::numeric(18, 2)
        as minimum_payment,
    nullif(extracted_data ->> 'previous_balance', '')::numeric(18, 2) as previous_balance,
    nullif(extracted_data ->> 'collections', '')::numeric(18, 2) as collections
from {{ ref('silver_documents') }}
where parse_status = 'parsed'
  and extracted_data ->> 'document_type' in (
      'condominium_expense',
      'electricity_bill',
      'water_bill',
      'gas_bill',
      'property_tax_bill',
      'credit_card_statement'
  )

union all

select
    invoice_id,
    null::bigint as document_id,
    message_id as source_message_id,
    'internet_bill'::text as document_type,
    'IPLAN Hogar'::text as issuer,
    null::text as unit,
    period,
    issue_date,
    first_due_date,
    first_due_amount,
    null::date as second_due_date,
    null::numeric(18, 2) as second_due_amount,
    'single'::text as due_date_kind,
    first_due_amount as total_amount,
    null::numeric(18, 2) as foreign_total_amount,
    null::text as foreign_currency,
    null::numeric(18, 2) as minimum_payment,
    null::numeric(18, 2) as previous_balance,
    null::numeric(18, 2) as collections
from iplan_invoices
