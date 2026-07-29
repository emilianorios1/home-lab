{{ config(schema='gold', alias='documents') }}

select
    d.document_id,
    d.original_filename,
    d.sha256,
    d.storage_path,
    d.byte_size,
    d.sender,
    d.subject,
    d.received_at,
    d.parse_status,
    d.parser_name,
    d.parser_version,
    d.error_message,
    coalesce(i.document_type, e.document_type) as document_type,
    coalesce(i.issuer, e.issuer) as issuer,
    i.unit,
    coalesce(i.period, e.period) as period,
    coalesce(i.issue_date, e.issue_date) as issue_date,
    i.first_due_date,
    i.first_due_amount,
    i.second_due_date,
    i.second_due_amount,
    i.due_date_kind,
    coalesce(i.total_amount, e.total_amount_ars) as total_amount,
    coalesce(i.foreign_total_amount, e.foreign_total_amount)
        as foreign_total_amount,
    coalesce(i.foreign_currency, e.foreign_currency) as foreign_currency,
    i.minimum_payment
from {{ ref('silver_documents') }} d
left join {{ ref('silver_invoices') }} i using (document_id)
left join {{ ref('gold_export_invoices') }} e using (document_id)
