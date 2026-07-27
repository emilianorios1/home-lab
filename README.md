# home-lab

Plataforma local para integrar movimientos financieros y documentos recibidos por
Gmail. Usa PostgreSQL, dbt y Streamlit con una arquitectura medallion.

## Arquitectura

```text
Mercado Pago CSV ───────────────┐
                               ▼
Gmail API ──► PDF/metadata ──► Bronze ──► parser PDF ──► Silver ──► Gold
                                                          │          │
                                                          └────┬─────┘
                                                               ▼
                                                    Streamlit (solo lectura)
```

- **Bronze** conserva fuentes reproducibles: movimientos originales, mensajes,
  adjuntos, texto extraído y resultados versionados del parser.
- **Silver** normaliza movimientos, documentos, facturas, vencimientos y conceptos.
- **Gold** disponibiliza movimientos, obligaciones, documentos y candidatos de
  conciliación.

Los PDF viven fuera de PostgreSQL en almacenamiento content-addressed. La base sólo
guarda su ruta relativa, SHA-256, tamaño, tipo y trazabilidad. Un correo se deduplica
por `message_id`, un adjunto por `message_id + attachment_id` y un documento por su
hash.

## Puesta en marcha

Copiá la configuración y levantá PostgreSQL:

```bash
cp .env.example .env
docker compose up -d postgres
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/home-lab init-db
```

Los datos financieros, documentos y secretos están excluidos de Git.

## Importación de Mercado Pago

```bash
.venv/bin/home-lab import-account-statement data/raw/account_statement.csv
.venv/bin/home-lab transform
```

Las importaciones nuevas se escriben en `bronze`. Al inicializar una instalación
existente, los lotes previos del esquema legado `raw` se copian sin eliminar el
origen.

## Configurar Gmail

La integración solicita únicamente acceso de lectura:

```text
https://www.googleapis.com/auth/gmail.readonly
```

1. En un proyecto de Google Cloud, habilitá Gmail API.
2. Creá un cliente OAuth para aplicación de escritorio.
3. Descargá el JSON como `secrets/gmail_client_secret.json`.
4. Autorizá la cuenta desde una sesión local:

   ```bash
   .venv/bin/home-lab gmail-auth
   ```

El token se guarda en `secrets/gmail_token.json` con permisos restringidos. No se
almacena la contraseña de Gmail.

El filtro predeterminado se configura en `.env`:

```dotenv
GMAIL_QUERY=from:no_reply@zetace.com.ar has:attachment filename:pdf
```

Para ejecutar el flujo completo:

```bash
.venv/bin/home-lab sync-gmail
```

Ese comando descarga adjuntos nuevos, procesa documentos pendientes y ejecuta
`dbt build`. Es idempotente: repetirlo no duplica correos ni PDF.

### Automatización

El script usa `flock` para impedir ejecuciones superpuestas:

```bash
scripts/sync-gmail.sh
```

Ejemplo de cron diario a las 07:15:

```cron
15 7 * * * /home/emiliano/home-lab/scripts/sync-gmail.sh >> /home/emiliano/home-lab/data/gmail-sync.log 2>&1
```

## Parser de expensas Zeta

El parser `zetace_expenses` extrae:

- consorcio, unidad, período y fecha de emisión;
- primer y segundo vencimiento con sus importes;
- expensas generales y extraordinarias;
- saldo anterior y cobranzas.

Cada resultado conserva nombre y versión del parser. Los estados posibles son
`parsed`, `unsupported` y `failed`, permitiendo corregir el parser y reprocesar sin
volver a consultar Gmail.

Para probar o recuperar un PDF local:

```bash
.venv/bin/home-lab import-document /ruta/al/documento.pdf
.venv/bin/home-lab transform
```

## Modelos de datos

Tablas y vistas principales:

```text
bronze.gmail_messages
bronze.gmail_attachments
bronze.document_parse_results
bronze.mercadopago_account_statements

silver.movements
silver.documents
silver.invoices
silver.invoice_due_dates
silver.invoice_line_items

gold.movements
gold.bills
gold.documents
gold.movement_document_candidates
```

Una factura es una obligación y no un movimiento realizado. Gold conserva esa
separación y genera candidatos de conciliación cuando coinciden el importe y una
ventana razonable alrededor del vencimiento.

## Dashboard

Construí Gold y levantá la aplicación:

```bash
.venv/bin/home-lab transform
docker compose up -d --build dashboard
```

Abrí [http://localhost:8501](http://localhost:8501). El dashboard ofrece:

- resumen y movimientos financieros;
- documentos y facturas;
- vencimientos e importes;
- descarga del PDF original;
- estado y errores de parsing.

El almacenamiento documental se monta como sólo lectura dentro del contenedor.

## Validación

```bash
.venv/bin/python -m pytest
.venv/bin/home-lab transform
```

dbt valida claves, relaciones, estados aceptados y que los conceptos de una expensa
sumen el importe del primer vencimiento.

## Estructura Python

Todo el código pertenece al namespace `home_lab` y las integraciones están agrupadas
por fuente o responsabilidad:

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
│   └── importer.py
├── documents/
│   ├── pdf.py
│   ├── storage.py
│   └── parsers/
└── dashboard/
```

Mercado Pago conserva dentro de su propio módulo toda la lectura y carga CSV. Gmail
separa llamadas externas, persistencia Bronze y orquestación, evitando paquetes
genéricos como `core` o `integrations`.
