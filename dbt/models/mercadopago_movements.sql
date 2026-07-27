select
    id,
    batch_id,
    release_date,
    transaction_type,
    reference_id,
    transaction_net_amount,
    partial_balance,
    case
        when transaction_net_amount < 0
            and transaction_type ilike '%Bled Cesar Adrian%'
            then 'Alquiler'
        when transaction_net_amount < 0
            then 'Sin categorizar'
        else null
    end as category
from {{ source('raw', 'mercadopago_account_statements') }}
