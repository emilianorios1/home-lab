{{ config(schema='gold', alias='shared_expense_items') }}

with invoice_dues as (
    select
        i.invoice_id,
        i.document_id,
        i.document_type,
        i.issuer,
        i.due_date_kind,
        d.due_number,
        d.due_date,
        d.amount,
        p.source_movement_id,
        p.payment_date,
        p.paid_amount,
        p.confidence
    from {{ ref('silver_invoices') }} i
    join {{ ref('silver_invoice_due_dates') }} d using (invoice_id)
    left join {{ ref('gold_bill_payments') }} p
      on p.invoice_id = d.invoice_id
     and p.due_number = d.due_number
    where i.document_type in (
        'condominium_expense',
        'electricity_bill',
        'water_bill',
        'gas_bill',
        'property_tax_bill'
    )
),

alternative_choice as (
    select
        invoice_id,
        coalesce(
            min(due_number) filter (where payment_date is not null),
            min(due_number) filter (where current_date <= due_date),
            max(due_number)
        ) as selected_due_number
    from invoice_dues
    where due_date_kind = 'alternative'
    group by invoice_id
),

selected_dues as (
    select d.*
    from invoice_dues d
    left join alternative_choice a using (invoice_id)
    where d.due_date_kind = 'installment'
       or (d.due_date_kind = 'single' and d.due_number = 1)
       or (
           d.due_date_kind = 'alternative'
           and d.due_number = a.selected_due_number
       )
),

automatic_items as (
    select
        date_trunc('month', due_date)::date as summary_month,
        case document_type
            when 'condominium_expense' then 'Expensas'
            when 'electricity_bill' then 'Luz'
            when 'water_bill' then 'Agua'
            when 'gas_bill' then 'Gas'
            when 'property_tax_bill' then 'TGI'
        end as category,
        invoice_id,
        document_id,
        issuer,
        due_number,
        due_date,
        amount as expected_amount,
        payment_date,
        paid_amount,
        confidence,
        case when payment_date is null then 'pending' else 'paid' end as payment_status
    from selected_dues
),

manual_items as (
    select
        summary_month,
        category,
        null::bigint as invoice_id,
        null::bigint as document_id,
        issuer,
        null::integer as due_number,
        due_date,
        expected_amount,
        payment_date,
        paid_amount,
        case when payment_status = 'paid' then 1.00 else null end::numeric(4, 2)
            as confidence,
        payment_status
    from {{ source('bronze', 'manual_shared_expenses') }}
)

select * from automatic_items
union all
select * from manual_items
