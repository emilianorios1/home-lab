# home-lab

Plataforma local para importar actividad financiera y documentos del hogar,
normalizarlos en PostgreSQL con dbt y consultarlos desde un dashboard Streamlit.
Usa Python 3.12, PostgreSQL 17 y una arquitectura Bronze/Silver/Gold.

## Arquitectura

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

- **Bronze** conserva fuentes reproducibles y la trazabilidad de cada ingesta.
- **Silver** normaliza movimientos, documentos, facturas, vencimientos y
  conceptos.
- **Gold** publica movimientos, obligaciones, documentos y candidatos de
  conciliación listos para consultar.

Los PDF viven fuera de PostgreSQL en almacenamiento content-addressed. La base
sólo guarda su metadata y trazabilidad. Las ingestas son idempotentes y las
escrituras del dashboard se limitan a interfaces explícitas de carga manual.

La explicación completa está en
[`docs/architecture.md`](docs/architecture.md).

## Funcionalidades

- Importación de movimientos mediante la API de reportes de Mercado Pago.
- Importación y validación de resúmenes de cuenta de Mercado Pago.
- Lectura de Gmail y descarga segura de documentos financieros.
- Facturas de EPE, ASSA y Litoral Gas, expensas Zeta y resúmenes de Naranja X.
- Importación y seguimiento mensual/anual de Facturas E emitidas en ARCA.
- Laboratorio de emisión Factura E con WSFEX a través del sandbox de Afip SDK.
- Descarga de boletas de TGI desde SIAT Rosario.
- Normalización y validación del modelo mediante dbt.
- Conciliación de obligaciones con pagos.
- Resumen de gastos compartidos con carga manual del alquiler bruto.
- Consulta de movimientos y documentos desde Streamlit.

La configuración y los comandos propios de cada fuente están en
[`docs/integrations.md`](docs/integrations.md).

## Desarrollo local

No sobrescribas un `.env` existente. Para preparar un checkout nuevo:

```bash
test -f .env || cp .env.example .env
docker compose up -d postgres
python3 -m venv .venv
.venv/bin/pip install --constraint requirements.lock -e '.[dev]'
.venv/bin/home-lab init-db
```

También se puede levantar el entorno de desarrollo completo con:

```bash
scripts/dev-up.sh
```

El dashboard de desarrollo queda en `http://localhost:8502` y PostgreSQL en
`127.0.0.1:5432`. Los datos financieros, documentos y secretos están excluidos
de Git.

Cada worktree puede levantar un entorno completamente aislado:

```bash
scripts/init-worktree.sh
scripts/dev-up.sh
.venv/bin/python -m pytest
```

El inicializador crea una `.env` y una `.venv` propias, con credenciales, puertos,
imagen, red, volumen PostgreSQL y directorio de datos separados del checkout
principal y de los demás worktrees. El dashboard de desarrollo monta los PDF de
producción en modo sólo lectura, sin duplicarlos. En el primer `dev-up.sh`, la
base aislada se inicializa con un backup tomado de producción en ese momento y
luego se aplican el esquema y los modelos dbt de la rama. La URL asignada al
dashboard se muestra al terminar.

## Flujos habituales

```bash
# Sincronizar documentos de Gmail
.venv/bin/home-lab sync-gmail

# Sincronizar el día anterior de Mercado Pago
.venv/bin/home-lab sync-mercadopago

# Descargar boletas nuevas de TGI
.venv/bin/home-lab sync-siat-tgi

# Importar una o más Facturas E locales
.venv/bin/home-lab import-document /ruta/factura-1.pdf /ruta/factura-2.pdf

# Reconstruir y validar Silver/Gold
.venv/bin/home-lab transform

# Levantar el dashboard
docker compose up -d --build dashboard
```

Las sincronizaciones también tienen scripts preparados para cron y protegidos
con `flock`. Consultá la
[guía de integraciones](docs/integrations.md) para configurarlas.

## Dashboard

Después de construir Gold y levantar la aplicación:

```bash
.venv/bin/home-lab transform
docker compose up -d --build dashboard
```

Abrí [http://localhost:8501](http://localhost:8501). Desde otro dispositivo de
la red local, usá `http://<ip-local-de-la-pc>:8501`.

La aplicación permite revisar movimientos, obligaciones, conciliaciones,
documentos, vencimientos, Facturas E y gastos compartidos, además de cargar el
alquiler bruto mensual. El laboratorio de Factura E está fijado a desarrollo y
sus CAE de prueba no se mezclan con los totales reales. El almacenamiento
documental se monta como sólo lectura dentro del contenedor.

La lógica funcional y las pantallas están documentadas en
[`docs/dashboard.md`](docs/dashboard.md).

## Documentación

| Guía | Contenido |
| --- | --- |
| [Arquitectura](docs/architecture.md) | Capas, almacenamiento, idempotencia y estructura Python |
| [Integraciones](docs/integrations.md) | Credenciales, fuentes, parsers, sincronización y cron |
| [Modelo de datos](docs/data-model.md) | Tablas principales, obligaciones y conciliación |
| [Dashboard](docs/dashboard.md) | Gastos compartidos y superficies de consulta |
| [Operación](docs/operations.md) | Producción, logs, backups, restauración y CI/CD |

## Validación

```bash
.venv/bin/python -m pytest
.venv/bin/home-lab transform
```

dbt valida claves, relaciones, estados aceptados y reglas de consistencia del
modelo. Los detalles se encuentran en
[`docs/data-model.md`](docs/data-model.md).
