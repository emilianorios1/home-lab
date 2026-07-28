{{ config(schema='silver', alias='movements') }}

with ranked_movements as (
    select
        movements.*,
        row_number() over (
            partition by
                coalesce(
                    movements.reference_id,
                    '__row__' || movements.id::text
                ),
                movements.release_date,
                movements.transaction_net_amount
            order by
                case
                    when coalesce(movements.transaction_type, '') ~
                         '^(SETTLEMENT|PAYOUTS?|TIP|WITHDRAWAL|REFUND)$'
                        then 2
                    else 1
                end,
                batches.imported_at desc,
                movements.id desc
        ) as movement_rank
    from {{ source('bronze', 'mercadopago_account_statements') }} movements
    join {{ source('bronze', 'import_batches') }} batches
      on batches.id = movements.batch_id
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
            when transaction_type ilike '%Naranja X%'
              or transaction_type ilike '%Tarjeta Naranja%' then 'Tarjeta Naranja'
            else 'Sin categorizar'
        end as explicit_category
    from ranked_movements
    where movement_rank = 1
),

known_amount_categories as (
    select
        abs(transaction_net_amount) as known_amount,
        min(explicit_category) as known_category
    from categorized_movements
    where explicit_category in (
        'Alquiler', 'Expensas', 'Luz', 'Agua', 'Gas', 'TGI', 'Tarjeta Naranja'
    )
    group by abs(transaction_net_amount)
    having count(distinct explicit_category) = 1
)

select
    'mercadopago'::text as source,
    movements.id as source_movement_id,
    movements.batch_id,
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
