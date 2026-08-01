# House Ledger

Plataforma local para importar actividad financiera y documentos del hogar,
normalizarlos en PostgreSQL con dbt y consultarlos desde Streamlit. Usa Python
3.12, PostgreSQL 17 y una arquitectura Bronze/Silver/Gold.

El paquete Python y el comando `home-lab` conservan su nombre original por
compatibilidad.

## Funcionalidades

- Importación de movimientos de Mercado Pago y carga validada de sus resúmenes.
- Lectura segura de Gmail y descarga de boletas de TGI desde SIAT Rosario.
- Parsing versionado de facturas, expensas, Internet y tarjetas.
- Seguimiento de Facturas E y laboratorio de emisión WSFEX en sandbox.
- Conciliación de obligaciones con pagos y resumen de gastos compartidos.
- Consulta de movimientos, documentos y operaciones desde Streamlit.

Los PDF viven fuera de PostgreSQL en almacenamiento content-addressed. Bronze
conserva las fuentes, Silver las normaliza y Gold publica las vistas de consulta.
Las ingestas son idempotentes y mantienen separadas las obligaciones de los
pagos.

## Inicio rápido

No sobrescribas un `.env` existente:

```bash
test -f .env || cp .env.example .env
python3 -m venv .venv
.venv/bin/pip install --constraint requirements.lock -e '.[dev]'
scripts/dev-up.sh
```

`dev-up.sh` levanta PostgreSQL y ejecuta el esquema y `dbt build`. Para iniciar
también el dashboard y el runner interno:

```bash
scripts/dev-up.sh --full
```

En un worktree enlazado, ejecutá antes `scripts/init-worktree.sh`. Si una prueba
necesita datos representativos, `scripts/dev-up.sh --snapshot` restaura una copia
aislada de producción; el modo predeterminado usa una base vacía.

## Flujos habituales

```bash
.venv/bin/home-lab sync-gmail
.venv/bin/home-lab sync-mercadopago
.venv/bin/home-lab sync-siat-tgi
.venv/bin/home-lab import-document /ruta/factura.pdf
.venv/bin/home-lab transform
```

Las sincronizaciones también se pueden ejecutar manualmente desde
**Operaciones** en el dashboard.

## Documentación

| Guía | Contenido |
| --- | --- |
| [Arquitectura](docs/architecture.md) | Capas, trazabilidad y estructura Python |
| [Integraciones](docs/integrations.md) | Fuentes, credenciales, parsers y sincronización |
| [Modelo de datos](docs/data-model.md) | Tablas, obligaciones y conciliación |
| [Dashboard](docs/dashboard.md) | Pantallas y cálculos funcionales |
| [Operación](docs/operations.md) | Desarrollo, producción, backups y CI/CD |

## Validación

```bash
.venv/bin/python -m pytest
.venv/bin/home-lab transform
docker compose config
```
