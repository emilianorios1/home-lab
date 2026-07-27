{{ config(schema='silver', alias='documents') }}

with ranked_parses as (
    select
        p.*,
        row_number() over (
            partition by p.attachment_id
            order by p.parsed_at desc, p.id desc
        ) as parse_rank
    from {{ source('bronze', 'document_parse_results') }} p
)

select
    a.id as document_id,
    a.message_id,
    a.original_filename,
    a.mime_type,
    a.byte_size,
    a.sha256,
    a.storage_path,
    a.ingested_at,
    m.sender,
    m.subject,
    m.received_at,
    p.parser_name,
    p.parser_version,
    coalesce(p.status, 'pending') as parse_status,
    p.page_count,
    p.extracted_data,
    p.error_message,
    p.parsed_at
from {{ source('bronze', 'gmail_attachments') }} a
join {{ source('bronze', 'gmail_messages') }} m using (message_id)
left join ranked_parses p
    on p.attachment_id = a.id
   and p.parse_rank = 1
