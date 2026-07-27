select *
from {{ ref('mercadopago_movements') }}
where transaction_net_amount < 0
  and transaction_type ilike '%Bled Cesar Adrian%'
  and category is distinct from 'Alquiler'
