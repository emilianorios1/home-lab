{{ config(schema='silver', alias='movements') }}

with statement_coverage as (
    select
        id as statement_id,
        period_start,
        period_end
    from {{ source('bronze', 'financial_statements') }}
    where provider = 'mercadopago'
      and account_key = 'primary'
      and statement_type = 'account_statement'
),

statement_movements as (
    select
        'statement'::text as source_origin,
        'statement:' || movements.statement_id::text || ':' ||
            lpad(movements.line_number::text, 8, '0') as source_movement_id,
        null::uuid as batch_id,
        movements.statement_id,
        movements.release_date,
        movements.transaction_type,
        movements.reference_id,
        movements.transaction_net_amount,
        movements.partial_balance,
        statements.imported_at,
        1 as source_priority
    from {{ source('bronze', 'mercadopago_statement_movements') }} movements
    join {{ source('bronze', 'financial_statements') }} statements
      on statements.id = movements.statement_id
),

legacy_movements as (
    select
        case
            when batches.source_filename like 'mercadopago-api-%'
                then 'api'
            else 'legacy_statement'
        end as source_origin,
        'legacy:' || movements.id::text as source_movement_id,
        movements.batch_id,
        null::uuid as statement_id,
        movements.release_date,
        movements.transaction_type,
        movements.reference_id,
        movements.transaction_net_amount,
        movements.partial_balance,
        batches.imported_at,
        case
            when batches.source_filename like 'mercadopago-api-%' then 3
            else 2
        end as source_priority
    from {{ source('bronze', 'mercadopago_account_statements') }} movements
    join {{ source('bronze', 'import_batches') }} batches
      on batches.id = movements.batch_id
),

legacy_statement_movements as (
    select *
    from legacy_movements legacy
    where source_origin = 'legacy_statement'
      and not exists (
          select 1
          from statement_coverage coverage
          where legacy.release_date
                between coverage.period_start and coverage.period_end
      )
),

manual_candidates as (
    select * from statement_movements
    union all
    select * from legacy_statement_movements
),

ranked_manual_movements as (
    select
        *,
        row_number() over (
            partition by
                coalesce(reference_id, source_movement_id),
                release_date,
                transaction_net_amount
            order by source_priority, imported_at desc, source_movement_id desc
        ) as movement_rank
    from manual_candidates
),

manual_movements as (
    select *
    from ranked_manual_movements
    where movement_rank = 1
),

legacy_statement_coverage as (
    select
        min(release_date) as period_start,
        max(release_date) as period_end
    from legacy_statement_movements
    group by batch_id
),

manual_coverage as (
    select period_start, period_end from statement_coverage
    union all
    select period_start, period_end from legacy_statement_coverage
),

api_candidates as (
    select
        'api'::text as source_origin,
        'api:' || movements.id::text as source_movement_id,
        movements.batch_id,
        null::uuid as statement_id,
        movements.release_date,
        movements.transaction_type,
        movements.reference_id,
        movements.transaction_net_amount,
        movements.partial_balance,
        batches.imported_at,
        3 as source_priority
    from {{ source('bronze', 'mercadopago_api_movements') }} movements
    join {{ source('bronze', 'import_batches') }} batches
      on batches.id = movements.batch_id

    union all

    select * from legacy_movements where source_origin = 'api'
),

numbered_api_movements as (
    select
        *,
        row_number() over (
            partition by
                batch_id,
                release_date,
                transaction_net_amount,
                coalesce(reference_id, ''),
                coalesce(transaction_type, '')
            order by source_movement_id
        ) as signature_occurrence
    from api_candidates
),

ranked_api_movements as (
    select
        *,
        row_number() over (
            partition by
                case
                    when reference_id is not null
                        then 'reference:' || reference_id
                    else 'signature:' ||
                        coalesce(release_date::text, '') || ':' ||
                        coalesce(transaction_net_amount::text, '') || ':' ||
                        coalesce(transaction_type, '') || ':' ||
                        signature_occurrence::text
                end,
                release_date,
                transaction_net_amount
            order by imported_at desc, source_movement_id desc
        ) as movement_rank
    from numbered_api_movements
),

canonical_movements as (
    select
        source_origin,
        source_movement_id,
        batch_id,
        statement_id,
        release_date,
        transaction_type,
        reference_id,
        transaction_net_amount,
        partial_balance
    from manual_movements

    union all

    select
        source_origin,
        source_movement_id,
        batch_id,
        statement_id,
        release_date,
        transaction_type,
        reference_id,
        transaction_net_amount,
        partial_balance
    from ranked_api_movements api
    where movement_rank = 1
      and not exists (
          select 1
          from manual_coverage coverage
          where api.release_date between coverage.period_start and coverage.period_end
      )
),

categorized_movements as (
    select
        *,
        case
            when transaction_net_amount >= 0 then null
            when transaction_type ilike '%Bled Cesar Adrian%' then 'Alquiler'
            when transaction_type ilike '%Banco Roela%'
              or transaction_type ilike '%SIRO%' then 'Expensas'
            when transaction_type ilike '%Litoral Gas%' then 'Gas'
            when transaction_type ilike '%Www.munipos%'
              or transaction_type ilike '%Aguas Santafesinas%' then 'Agua'
            when transaction_type ilike '%Municipalidad de rosar%' then 'TGI'
            when transaction_type ilike '%Empresa Provincial de la Energía%'
              or transaction_type ilike '%EPE%' then 'Luz'
            when transaction_type ilike '%Iplan%' then 'Internet'
            when transaction_type ilike '%Naranja X%'
              or transaction_type ilike '%Tarjeta Naranja%' then 'Tarjeta Naranja'
            else 'Sin categorizar'
        end as explicit_category
    from canonical_movements
),

known_amount_categories as (
    select
        abs(transaction_net_amount) as known_amount,
        min(explicit_category) as known_category
    from categorized_movements
    where explicit_category in (
        'Alquiler', 'Expensas', 'Luz', 'Agua', 'Gas', 'TGI', 'Internet',
        'Tarjeta Naranja'
    )
    group by abs(transaction_net_amount)
    having count(distinct explicit_category) = 1
)

select
    'mercadopago'::text as source,
    movements.source_origin,
    movements.source_movement_id,
    movements.batch_id,
    movements.statement_id,
    movements.release_date,
    movements.transaction_type as description,
    movements.reference_id,
    movements.transaction_net_amount as amount,
    movements.partial_balance as running_balance,
    case
        when movements.explicit_category = 'Sin categorizar'
            then coalesce(known.known_category, movements.explicit_category)
        else movements.explicit_category
    end as category
from categorized_movements movements
left join known_amount_categories known
  on known.known_amount = abs(movements.transaction_net_amount)
