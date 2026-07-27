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
    i.document_type,
    i.issuer,
    i.unit,
    i.period,
    i.issue_date,
    i.first_due_date,
    i.first_due_amount,
    i.second_due_date,
    i.second_due_amount
from {{ ref('silver_documents') }} d
left join {{ ref('silver_invoices') }} i using (document_id)
