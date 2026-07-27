{{ config(schema='silver', alias='movements') }}

select
    'mercadopago'::text as source,
    id as source_movement_id,
    batch_id,
    release_date,
    transaction_type as description,
    reference_id,
    transaction_net_amount as amount,
    partial_balance as running_balance,
    case
        when transaction_net_amount < 0
            and transaction_type ilike '%Bled Cesar Adrian%'
            then 'Alquiler'
        when transaction_net_amount < 0
            then 'Sin categorizar'
        else null
    end as category
from {{ source('bronze', 'mercadopago_account_statements') }}
