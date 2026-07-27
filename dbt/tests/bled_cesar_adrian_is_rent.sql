select *
from {{ ref('silver_movements') }}
where amount < 0
  and description ilike '%Bled Cesar Adrian%'
  and category <> 'Alquiler'
