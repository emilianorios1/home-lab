{{ config(schema='gold', alias='movements') }}

select *
from {{ ref('silver_movements') }}
