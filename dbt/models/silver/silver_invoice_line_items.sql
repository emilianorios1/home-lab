{{ config(schema='silver', alias='invoice_line_items') }}

select
    d.document_id as invoice_id,
    concept.ordinality::integer as line_number,
    concept.value ->> 'code' as concept_code,
    (concept.value ->> 'amount')::numeric(18, 2) as amount
from {{ ref('silver_documents') }} d
cross join lateral jsonb_array_elements(
    coalesce(d.extracted_data -> 'concepts', '[]'::jsonb)
) with ordinality as concept(value, ordinality)
where d.parse_status = 'parsed'
