# Operación de desarrollo y producción

La instalación usa dos proyectos Docker independientes. No comparten red,
credenciales ni volúmenes:

| Entorno | Proyecto | Dashboard | PostgreSQL | Persistencia |
|---|---|---|---|---|
| Desarrollo | `home-lab-dev` | `127.0.0.1:8502` | `127.0.0.1:5432` | volumen `home-lab-dev-postgres-data` y `./data` |
| Producción | `home-lab-prod` | `0.0.0.0:8501` | sólo red Docker interna | volumen `home-lab-prod-postgres-data` y `~/.local/share/home-lab` |

## Desarrollo

```bash
test -f .env || cp .env.example .env
python3 -m venv .venv
.venv/bin/pip install --constraint requirements.lock -e '.[dev]'
scripts/dev-up.sh
```

El modo predeterminado levanta PostgreSQL y ejecuta `home-lab init-db` y `dbt
build` desde el virtualenv local. Para probar la interfaz y las operaciones:

```bash
scripts/dev-up.sh --full
```

Ese modo construye la imagen y espera los healthchecks de Streamlit y del runner.
El código de `src/` se monta en ambos contenedores y Streamlit recarga los cambios.

En un worktree enlazado, inicializá una sola vez su entorno aislado antes de usar
los mismos comandos:

```bash
scripts/init-worktree.sh
scripts/dev-up.sh
```

La `.env` generada contiene credenciales y puertos exclusivos. Compose separa el
proyecto, la imagen, la red y el volumen PostgreSQL; `data/` y `.venv` pertenecen
al propio worktree. No se inicia el dashboard ni se copian datos productivos por
defecto.

Cuando una prueba necesite datos representativos, usá
`scripts/dev-up.sh --snapshot` como primer arranque. El backup queda dentro del
volumen aislado y nunca debe exportarse, imprimirse ni incorporarse al
repositorio. Los PDF no se copian: el dashboard los monta desde producción en
modo sólo lectura. `scripts/dev-up.sh --snapshot --full` combina el snapshot con
la interfaz completa.

Comandos cotidianos:

```bash
# Interfaz completa, estado y logs
scripts/dev-up.sh --full
docker compose ps
docker compose logs -f dashboard
docker compose logs -f sync-runner

# Tests
.venv/bin/pytest

# Detener el stack sin borrar la base
docker compose --env-file .env down
```

`docker compose down -v` elimina la base de desarrollo completa; no es un comando
normal de operación.

## Primera instalación productiva

Desde el checkout que se quiera desplegar:

```bash
scripts/install-production.sh
```

El instalador:

1. genera `~/.config/home-lab/prod.env` con una contraseña aleatoria;
2. construye una imagen local;
3. crea la base productiva, aplica el esquema y ejecuta `dbt build`;
4. arranca el dashboard y el runner interno, y espera sus healthchecks;
5. instala un servicio systemd de usuario, un backup diario y una prueba
   mensual de restauración;
6. intenta habilitar *lingering* para que siga activo sin una sesión abierta.

Si el último paso necesita privilegios:

```bash
sudo loginctl enable-linger "$USER"
```

La configuración y los secretos quedan en `~/.config/home-lab`; los documentos y
backups en `~/.local/share/home-lab`. Ambos sobreviven a nuevos checkouts y nunca
se incorporan a la imagen.

La aplicación queda en `http://IP-DE-LA-NOTEBOOK:8501`. Streamlit no aporta
autenticación en este despliegue: el puerto debe permitirse sólo en una red local
confiable. Las sincronizaciones requieren además la clave
`HOME_LAB_OPERATIONS_PASSWORD`, generada en `prod.env` si todavía no existe.
PostgreSQL y el runner no publican puertos productivos.

## Operación productiva

```bash
# Estado, logs y healthchecks
systemctl --user status home-lab-production.service
~/.config/home-lab/production-compose.sh ps
~/.config/home-lab/production-compose.sh logs -f --tail=200 dashboard
~/.config/home-lab/production-compose.sh logs -f --tail=200 sync-runner

# Recrear la aplicación después de cambiar su clave de operaciones
~/.config/home-lab/production-compose.sh up -d --force-recreate dashboard

# Pedir una nueva clave sin mostrarla y recrear el dashboard
scripts/change-operations-password.sh

# Guardar un nuevo token de Afip SDK sin mostrarlo y recrear el dashboard
scripts/set-afip-sdk-access-token.sh

# Ejecutar ingestas con los mismos datos persistentes de producción
~/.config/home-lab/production-compose.sh run --rm tools sync-gmail
~/.config/home-lab/production-compose.sh run --rm tools sync-mercadopago
~/.config/home-lab/production-compose.sh run --rm tools sync-siat-tgi

# Ver los calendarios y ejecutar un backup ahora
systemctl --user list-timers home-lab-backup.timer
systemctl --user list-timers home-lab-backup-verify.timer
systemctl --user start home-lab-backup.service
```

Los secretos de Gmail deben copiarse a
`~/.config/home-lab/secrets/gmail_client_secret.json` y
`gmail_token.json`. Las demás credenciales se editan únicamente en
`~/.config/home-lab/prod.env`, cuyo modo debe permanecer en `0600`.
La clave de **Operaciones** se consulta o reemplaza en ese mismo archivo; nunca
debe incorporarse al repositorio. El token de Afip SDK se rota primero desde el
proveedor y luego se carga con `scripts/set-afip-sdk-access-token.sh`; no debe
pasarse como argumento ni quedar en el historial de la terminal.

Cada deploy productivo:

1. toma un backup consistente si ya existe una base;
2. baja la imagen indicada por digest;
3. espera que PostgreSQL esté sano;
4. ejecuta `home-lab init-db` y `dbt build`;
5. reemplaza Streamlit y el runner, y espera sus healthchecks;
6. vuelve a la imagen anterior si el arranque falla.

Los logs Docker rotan a tres archivos de 10 MiB por servicio. Los backups se
validan con `pg_restore --list` y se retienen 14 días de forma predeterminada.
Una vez por mes, un backup nuevo también se restaura dentro de un PostgreSQL
temporal sin red ni almacenamiento persistente. La comprobación sólo valida el
esquema y no imprime datos.

### Restaurar un backup

Una restauración reemplaza estado y por eso no está automatizada. Primero se debe
detener el dashboard, conservar un backup del estado actual y verificar exactamente
el archivo a restaurar:

```bash
systemctl --user start home-lab-backup.service
~/.config/home-lab/production-compose.sh stop dashboard
ls -lh ~/.local/share/home-lab/backups
```

Después de elegir el dump, se puede recrear la base y cargarlo con `pg_restore`.
Conviene hacerlo en una ventana de mantenimiento y volver a ejecutar el contenedor
`migrate` antes de arrancar el dashboard.

## CI/CD

`.github/workflows/ci-cd.yaml` ejecuta en cada pull request:

- compilación de todos los módulos;
- verificación de dependencias;
- inicialización real de PostgreSQL;
- `dbt build`, incluidos los tests de datos;
- tests de pytest;
- validación de ambos Compose;
- build completo de la imagen.
- sintaxis de todos los scripts Bash.

Un push a `main` publica en GHCR una imagen con SBOM y la despliega por digest, no
por una etiqueta mutable. El deploy comprueba además el digest efectivo del
contenedor y el healthcheck a través del puerto publicado.

Las dependencias Python están fijadas en `requirements.lock`; CI, los worktrees y
la imagen productiva usan el mismo conjunto. Dependabot propone mensualmente las
actualizaciones de Python y GitHub Actions.

Para que GitHub pueda llegar a una notebook detrás de NAT hace falta registrar en
este equipo un runner **self-hosted** del repositorio, instalarlo como servicio y
asignarle la etiqueta `home-lab-prod`. El usuario del runner debe:

- poder ejecutar Docker sin `sudo`;
- ser el mismo usuario que instaló producción;
- tener acceso a `~/.config/home-lab/prod.env`;
- tener habilitado el servicio del runner al inicio.

Con GitHub CLI autenticado y permisos de administración sobre el repositorio, el
registro y el servicio se instalan de forma idempotente con:

```bash
scripts/install-github-runner.sh
```

`main` está protegida: requiere pull request, el check `Tests, dbt and image`,
conversaciones resueltas y una rama actualizada; no permite force-push ni borrado.
No exige aprobación humana porque el repositorio tiene un único mantenedor. El
environment `production` acepta únicamente despliegues desde `main`.

El repositorio sólo permite Actions propias de GitHub y las tres Actions de
Docker usadas por el workflow. Todas están fijadas a un commit completo. La
exigencia global de SHA se habilita después de que este workflow llegue a `main`,
para no invalidar ejecuciones del workflow anterior durante la transición.

## Chequeos rápidos

```bash
# Desarrollo y producción son proyectos diferentes
docker compose ls

# La base productiva no debe mostrar puertos publicados
~/.config/home-lab/production-compose.sh port postgres 5432

# Endpoint usado por Docker y CI/CD
curl --fail http://localhost:8501/_stcore/health
```
