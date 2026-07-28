{{ config(schema='silver', alias='documents') }}

with ranked_parses as (
    select
        p.*,
        row_number() over (
            partition by p.attachment_id
            order by p.parsed_at desc, p.id desc
        ) as parse_rank
    from {{ source('bronze', 'document_parse_results') }} p
),

document_candidates as (
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
        coalesce(p.extracted_data ->> 'source_parser', p.parser_name) as parser_name,
        coalesce(
            p.extracted_data ->> 'source_parser_version',
            p.parser_version
        ) as parser_version,
        coalesce(p.status, 'pending') as parse_status,
        p.page_count,
        p.extracted_data,
        p.error_message,
        p.parsed_at,
        row_number() over (
            partition by a.sha256
            order by
                case coalesce(p.status, 'pending')
                    when 'parsed' then 1
                    when 'pending' then 2
                    when 'unsupported' then 3
                    else 4
                end,
                m.received_at desc nulls last,
                a.id desc
        ) as document_rank
    from {{ source('bronze', 'gmail_attachments') }} a
    join {{ source('bronze', 'gmail_messages') }} m using (message_id)
    left join ranked_parses p
        on p.attachment_id = a.id
       and p.parse_rank = 1
)

select
    document_id,
    message_id,
    original_filename,
    mime_type,
    byte_size,
    sha256,
    storage_path,
    ingested_at,
    sender,
    subject,
    received_at,
    parser_name,
    parser_version,
    parse_status,
    page_count,
    extracted_data,
    error_message,
    parsed_at
from document_candidates
where document_rank = 1
