# home-lab

Base local para automatizar la gestión de costos, comenzando por la importación manual de extractos de cuenta de Mercado Pago.

## Arquitectura

```text
data/raw/account_statement.csv
            │
            ▼
 app/cli.py ──► pipelines/mercadopago_account_statement.py
                         │ transform(DataFrame)
                         ▼
                  core/core.py + core/etl.py
                         │
                         ▼
              PostgreSQL: raw.import_batches
                          raw.mercadopago_account_statements
                         │
                         ▼
                    dbt: analytics
                         │
                         ▼
          dashboard/ (Streamlit, solo lectura)
```

- `app/`: puntos de entrada. Hoy contiene el CLI para crear el esquema e importar un CSV.
- `core/core.py`: runner genérico que coordina la lectura, transformación, auditoría y carga atómica de un CSV.
- `core/etl.py`: helpers pequeños de pandas para validar CSV y cargar DataFrames.
- `core/database.py`: conexión a PostgreSQL e inicialización de las tablas raw.
- `pipelines/`: configuración y transformación específica de cada fuente. No contiene conexiones ni SQL de carga.
- `raw`: capa de datos sin reglas de negocio. Conserva movimientos tipados y el lote de archivo que los originó.
- `dbt/`: modelos y pruebas de la capa `analytics`, incluidas las reglas de categorización.
- `dashboard/`: interfaz Streamlit de solo lectura para visualizar flujo, saldos y movimientos.

La capa `analytics` contiene reglas de categorización versionadas y vistas derivadas para
que el dashboard muestre gastos por categoría sin alterar los datos raw. Actualmente,
los egresos destinados a `Bled Cesar Adrian` se categorizan como `Alquiler`; los demás
quedan como `Sin categorizar`.

## PostgreSQL local

1. Copiá la configuración de ejemplo si todavía no existe:

   ```bash
   cp .env.example .env
   ```

2. Levantá la base:

   ```bash
   docker compose up -d
   ```

3. Confirmá que esté disponible:

   ```bash
   docker compose ps
   docker compose exec postgres psql -U home_lab -d home_lab
   ```

Para detenerla, ejecutá `docker compose down`. Los datos viven en el volumen Docker `postgres_data` y se conservan al detener el servicio.

## Importaciones CSV

Dejá las exportaciones manuales de Mercado Pago en `data/raw/`. Ese contenido no se versiona para evitar publicar datos financieros. La futura automatización procesará esos archivos y luego incorporará una integración por API.

## Importador de Mercado Pago

El importador es un CLI de Python. Crea el esquema `raw` y carga el CSV sin aplicar reglas de negocio: conserva las columnas de Mercado Pago con montos y fechas tipados para PostgreSQL.

1. Creá el entorno e instalá dependencias:

   ```bash
   python3 -m venv .venv
   .venv/bin/pip install -e '.[dev]'
   ```

2. Inicializá el esquema:

   ```bash
   .venv/bin/python -m app.cli init-db
   ```

3. Importá un extracto de cuenta explícitamente:

   ```bash
   .venv/bin/python -m app.cli import-account-statement data/raw/account_statement.csv
   ```

4. Construí y validá la capa analítica:

   ```bash
   .venv/bin/python -m app.cli transform
   ```

Al importar otra vez el mismo nombre de archivo, el lote anterior se reemplaza de forma atómica. Los archivos con otro nombre se guardan como lotes independientes.

Podés correr los tests con:

```bash
.venv/bin/python -m pytest
```

### Agregar otra pipeline CSV

Una pipeline nueva sólo necesita declarar:

- las columnas esperadas y opciones de `pandas.read_csv`;
- los tipos de las columnas de destino;
- una función `transform(dataframe)`;
- una función `process(path)` que llame a `run_csv_pipeline`.

La lectura, conexión, creación del lote, transacción y carga con `DataFrame.to_sql`
quedan centralizadas en `core`. Si más adelante una fuente necesita API, archivos
grandes o una estrategia de carga diferente, se puede agregar esa capacidad sin
complicar las pipelines CSV existentes.

## Dashboard local

El dashboard Streamlit muestra flujo, saldo y movimientos del extracto de cuenta. Levantalo junto a PostgreSQL:

```bash
docker compose up -d --build
```

Abrí [http://localhost:8501](http://localhost:8501). El servicio queda expuesto únicamente en esta máquina y solo consulta datos; no modifica movimientos ni lotes importados.
