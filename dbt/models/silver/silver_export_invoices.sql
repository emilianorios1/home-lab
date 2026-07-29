{{ config(schema='silver', alias='export_invoices') }}

select
    document_id as invoice_id,
    document_id,
    extracted_data ->> 'document_type' as document_type,
    extracted_data ->> 'issuer' as issuer,
    extracted_data ->> 'point_of_sale' as point_of_sale,
    extracted_data ->> 'invoice_number' as invoice_number,
    concat(
        extracted_data ->> 'point_of_sale',
        '-',
        extracted_data ->> 'invoice_number'
    ) as invoice_key,
    (extracted_data ->> 'period')::date as period,
    (extracted_data ->> 'issue_date')::date as issue_date,
    (extracted_data ->> 'payment_date')::date as payment_date,
    extracted_data ->> 'foreign_currency' as foreign_currency,
    (extracted_data ->> 'foreign_total_amount')::numeric(18, 2)
        as foreign_total_amount,
    (extracted_data ->> 'exchange_rate')::numeric(18, 6) as exchange_rate,
    extracted_data ->> 'cae' as cae,
    (extracted_data ->> 'cae_due_date')::date as cae_due_date
from {{ ref('silver_documents') }}
where parse_status = 'parsed'
  and extracted_data ->> 'document_type' = 'export_service_invoice'
