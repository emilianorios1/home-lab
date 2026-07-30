# Modelo de datos

`home-lab` usa una arquitectura Bronze/Silver/Gold. Bronze conserva las fuentes
reproducibles, Silver normaliza sus entidades y Gold presenta modelos listos para
consulta.

## Tablas y vistas principales

```text
bronze.gmail_messages
bronze.gmail_attachments
bronze.document_parse_results
bronze.financial_statements
bronze.mercadopago_statement_movements
bronze.mercadopago_api_movements
bronze.mercadopago_account_statements
bronze.manual_monthly_rents
bronze.export_invoice_emissions
bronze.recurring_export_invoice_profile

silver.movements
silver.documents
silver.invoices
silver.invoice_due_dates
silver.invoice_line_items
silver.credit_card_transactions
silver.export_invoices

gold.movements
gold.bills
gold.documents
gold.movement_document_candidates
gold.credit_card_expenses
gold.export_invoices
```

## Obligaciones y movimientos

Una factura es una obligación, no un movimiento realizado. Gold conserva esa
separación y genera candidatos de conciliación cuando coinciden el importe y una
ventana razonable alrededor del vencimiento.

Los consumos de tarjeta se publican en `gold.credit_card_expenses` y permanecen
separados de `gold.movements`. Así se puede analizar cada compra sin duplicar el
gasto cuando posteriormente se paga el resumen.

Las Facturas E emitidas se normalizan en `silver.export_invoices` y se publican
en `gold.export_invoices` con su importe original, tipo de cambio histórico y
equivalente en pesos. No entran en `gold.bills`: son comprobantes de venta, no
obligaciones del hogar ni prueba de cobro.

`bronze.export_invoice_emissions` conserva únicamente las pruebas del sandbox
WSFEX: borrador, ID, número asignado, payload, respuesta y estado. No almacena el
access token ni el ticket de acceso. Las operaciones `dev` no alimentan
Silver/Gold para evitar que un comprobante inválido fiscalmente contamine los
controles reales.

`bronze.recurring_export_invoice_profile` mantiene los campos que se repiten
para un único salario recurrente. Fecha y tipo de cambio quedan fuera del perfil
para su revisión antes de cada emisión.

Los comprobantes históricos que ya no estén disponibles en su fuente pueden
registrarse localmente en `bronze.manual_shared_expenses`. Sus valores permanecen
en PostgreSQL y no se versionan en Git.

El alquiler bruto informado para cada mes se guarda en
`bronze.manual_monthly_rents`. La carga usa una fila por mes y las correcciones
actualizan esa misma fila, sin mezclar el importe informado con los movimientos
que comprueban su pago.

## Validación

Para reconstruir y validar Silver/Gold:

```bash
.venv/bin/home-lab transform
```

El flujo ejecuta `dbt build`. Los tests de dbt validan claves, relaciones,
estados aceptados y que los conceptos de una expensa sumen el importe del primer
vencimiento.

Los tests de comportamiento Python se ejecutan con:

```bash
.venv/bin/python -m pytest
```

## Lecturas relacionadas

- [Arquitectura](architecture.md)
- [Integraciones](integrations.md)
- [Dashboard](dashboard.md)
