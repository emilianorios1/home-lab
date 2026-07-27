# home-lab

Base local para automatizar la gestión de costos, comenzando por la importación manual de liquidaciones de Mercado Pago.

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

3. Importá un CSV explícitamente:

   ```bash
   .venv/bin/python -m app.cli import-mercadopago data/raw/reporte.csv
   ```

Al importar otra vez el mismo nombre de archivo, el lote anterior se reemplaza de forma atómica. Los archivos con otro nombre se guardan como lotes independientes.

Podés correr los tests con:

```bash
.venv/bin/python -m pytest
```
