# home-lab

Base local para automatizar la gestión de costos, comenzando por la importación manual de extractos de cuenta de Mercado Pago.

## Arquitectura

```text
data/raw/account_statement.csv
            │
            ▼
 app/cli.py ──► pipelines/mercadopago_account_statement.py
                         │
                         ▼
              PostgreSQL: raw.import_batches
                          raw.mercadopago_account_statements
                         │
                         ▼
          dashboard/ (Streamlit, solo lectura)
```

- `app/`: puntos de entrada. Hoy contiene el CLI para crear el esquema e importar un CSV.
- `core/`: piezas compartidas: configuración, conexión a PostgreSQL y logging.
- `pipelines/`: lógica específica de cada fuente de datos. El pipeline actual valida y carga `account_statement` en formato raw.
- `raw`: capa de datos sin reglas de negocio. Conserva movimientos tipados y el lote de archivo que los originó.
- `dashboard/`: interfaz Streamlit de solo lectura para visualizar flujo, saldos y movimientos.

La próxima capa será `analytics`: reglas de categorización versionadas (por ejemplo, `Netflix → Suscripciones`) y vistas o tablas derivadas para que el dashboard muestre gastos por categoría sin alterar los datos raw.

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

Al importar otra vez el mismo nombre de archivo, el lote anterior se reemplaza de forma atómica. Los archivos con otro nombre se guardan como lotes independientes.

Podés correr los tests con:

```bash
.venv/bin/python -m pytest
```

## Dashboard local

El dashboard Streamlit muestra flujo, saldo y movimientos del extracto de cuenta. Levantalo junto a PostgreSQL:

```bash
docker compose up -d --build
```

Abrí [http://localhost:8501](http://localhost:8501). El servicio queda expuesto únicamente en esta máquina y solo consulta datos; no modifica movimientos ni lotes importados.
