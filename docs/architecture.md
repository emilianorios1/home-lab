# Arquitectura

`home-lab` integra actividad financiera y documentos del hogar en PostgreSQL,
los transforma con dbt y los presenta en Streamlit. Las páginas de reporte son de
sólo lectura y las escrituras se limitan a interfaces explícitas de carga manual.

```text
Mercado Pago Reports API ───────┐
                               ▼
Gmail API ──► PDF/metadata ──► Bronze ──► parser PDF ──► Silver ──► Gold
SIAT TGI ───► boleta PDF ────────┘
                                                          │          │
                                                          └────┬─────┘
                                                               ▼
                                           Streamlit (consultas + carga manual)
```

## Capas de datos

- **Bronze** conserva fuentes reproducibles: movimientos originales, mensajes,
  adjuntos, texto extraído y resultados versionados del parser.
- **Silver** normaliza movimientos, documentos, obligaciones, Facturas E
  emitidas, vencimientos, conceptos y consumos de tarjetas.
- **Gold** disponibiliza movimientos, obligaciones, documentos, gastos y
  candidatos de conciliación listos para consultar.

Una factura recibida es una obligación y no un movimiento realizado. Una
Factura E emitida es una venta y tampoco demuestra por sí sola que haya sido
cobrada. Gold conserva separadas esas entidades y los movimientos de efectivo.

## Documentos y trazabilidad

Los PDF viven fuera de PostgreSQL en almacenamiento content-addressed. La base
sólo guarda su ruta relativa, SHA-256, tamaño, tipo y trazabilidad.

Un correo se deduplica por `message_id`, un adjunto por
`message_id + attachment_id` y un documento por su hash. Cada resultado de
parsing conserva el nombre y la versión del parser para poder corregirlo y
reprocesarlo sin volver a consultar la fuente.

Las descargas externas se restringen a endpoints de confianza, deben tener firma
PDF y respetan el límite de tamaño configurado.

## Estructura Python

Todo el código pertenece al namespace `home_lab`. Las integraciones están
agrupadas por fuente y mantienen separados el acceso HTTP, la persistencia, el
parsing y la orquestación:

```text
src/home_lab/
├── cli.py
├── config.py
├── database.py
├── gmail/
│   ├── client.py
│   ├── repository.py
│   └── pipeline.py
├── mercadopago/
│   ├── client.py
│   ├── importer.py
│   └── pipeline.py
├── siat/
├── documents/
│   ├── pdf.py
│   ├── storage.py
│   └── parsers/
└── dashboard/
```

Mercado Pago separa el cliente HTTP, la transformación/carga y la orquestación.
Gmail aplica la misma separación para llamadas externas, persistencia Bronze y
pipeline. Las nuevas fuentes siguen esa estructura en lugar de concentrarse en
paquetes genéricos.

Las consultas del dashboard permanecen separadas de las interfaces explícitas de
carga manual. Estas últimas persisten sus datos en Bronze para conservar
trazabilidad.

El esquema legado `raw` se mantiene como camino de compatibilidad para
instalaciones existentes. Su migración a Bronze es repetible y no elimina el
origen.

## Lecturas relacionadas

- [Integraciones](integrations.md)
- [Modelo de datos](data-model.md)
- [Dashboard](dashboard.md)
- [Operación de desarrollo y producción](operations.md)
