{{ config(schema='gold', alias='export_invoices') }}

select
    i.*,
    round(i.foreign_total_amount * i.exchange_rate, 2) as total_amount_ars,
    d.original_filename,
    d.storage_path
from {{ ref('silver_export_invoices') }} i
join {{ ref('silver_documents') }} d using (document_id)
