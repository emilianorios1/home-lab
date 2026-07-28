# home-lab

Plataforma local para integrar movimientos financieros y documentos recibidos por
Gmail. Usa PostgreSQL, dbt y Streamlit con una arquitectura medallion.

## Arquitectura

```text
Mercado Pago Reports API ───────┐
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

## Configurar Mercado Pago

La integración usa la API oficial de reportes de **Todas las transacciones**. No
consulta solamente ventas: el reporte incluye las operaciones aprobadas que
afectaron el dinero de la cuenta. Mercado Pago genera el reporte de manera
asíncrona; `home-lab` solicita el período, espera la tarea, descarga el resultado y
lo importa sin intervención manual.

### Obtener el Access Token

1. Ingresá a [Tus integraciones de Mercado
   Pago](https://www.mercadopago.com.ar/developers/panel/app) con la misma cuenta
   cuyos movimientos querés importar.
2. Creá una aplicación (por ejemplo, `home-lab`) o abrí una existente.
3. Entrá en **Producción > Credenciales de producción**. Si todavía no están
   activas, Mercado Pago solicitará rubro, sitio web, aceptación de términos y
   reCAPTCHA.
4. Copiá únicamente el **Access Token** de producción, que comienza normalmente
   con `APP_USR-`. No hace falta usar la Public Key, Client ID ni Client Secret.
5. Guardalo en el `.env` local, que está excluido de Git:

   ```dotenv
   MERCADOPAGO_ACCESS_TOKEN=APP_USR-tu-token-real
   ```

El token es una clave privada con acceso a información de la cuenta: no debe
pegarse en el código, el README, una captura ni un commit. Puede renovarse desde el
mismo panel si alguna vez queda expuesto.

La primera vez, configurá las columnas estables que necesita el importador:

```bash
.venv/bin/home-lab configure-mercadopago
```

Este comando crea o actualiza la configuración compartida del reporte en Mercado
Pago (columnas, separador, idioma y zona horaria); no activa una programación en
los servidores de Mercado Pago.

### Sincronizar movimientos

Para importar un período y reconstruir Silver/Gold:

```bash
.venv/bin/home-lab sync-mercadopago --from 2026-07-01 --to 2026-07-26
```

Sin fechas importa el día anterior, que es el modo recomendado para cron:

```bash
scripts/sync-mercadopago.sh
```

Ejemplo diario a las 06:30:

```cron
30 6 * * * /home/emiliano/home-lab/scripts/sync-mercadopago.sh >> /home/emiliano/home-lab/data/mercadopago-sync.log 2>&1
```

Repetir exactamente el mismo período reemplaza su lote anterior. Para un backfill,
usá períodos sin superposición para no cargar dos veces los mismos movimientos.
El formato oficial no incluye el saldo acumulado de cada fila, por lo que
`running_balance` queda vacío para registros obtenidos por API; ingresos, egresos,
flujo neto, categorías y conciliación siguen disponibles.

La importación manual anterior queda como herramienta de recuperación:

```bash
.venv/bin/home-lab import-account-statement data/raw/account_statement.csv
.venv/bin/home-lab transform
```

Las importaciones se escriben en `bronze`. Al inicializar una instalación existente,
los lotes previos del esquema legado `raw` se copian sin eliminar el origen.

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

El filtro predeterminado se configura en `.env`. Incluye adjuntos PDF de Zeta y
facturas enlazadas de EPE, Aguas Santafesinas y Litoral Gas:

```dotenv
GMAIL_QUERY={from:no_reply@zetace.com.ar from:oficinavirtual@epe.santafe.gov.ar from:facturadigital@aguassantafesinas.com from:factura@digital.litoralgas.com.ar} newer_than:30d
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

## Facturas de EPE

Los correos de EPE no adjuntan el documento. El flujo reconoce únicamente enlaces
del endpoint oficial de facturación de EPE, sigue su redirección a HTTPS, valida la
firma PDF y aplica el mismo límite de tamaño que a un adjunto. El parser
`epe_electricity_bill` extrae cliente, domicilio del suministro, emisión, consumo,
total y las dos cuotas con sus vencimientos. Las cuotas se publican como
vencimientos independientes para permitir su conciliación con movimientos.

## Facturas de ASSA y Litoral Gas

El flujo reconoce los botones de descarga enviados por Aguas Santafesinas y
Litoral Gas, decodifica localmente sus enlaces de seguimiento y sólo descarga
desde los endpoints de facturación permitidos. El parser de ASSA publica las dos
cuotas de la factura de agua; el de Litoral Gas publica su vencimiento único.
Ambos extraen cliente, período, emisión, domicilio, consumo e importe.

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
│   ├── client.py
│   ├── importer.py
│   └── pipeline.py
├── documents/
│   ├── pdf.py
│   ├── storage.py
│   └── parsers/
└── dashboard/
```

Mercado Pago separa el cliente HTTP, la transformación/carga y la orquestación.
Gmail aplica la misma separación para llamadas externas, persistencia Bronze y
pipeline, evitando paquetes genéricos como `core` o `integrations`.
