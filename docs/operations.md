# Operación de desarrollo y producción

La instalación usa dos proyectos Docker independientes. No comparten red,
credenciales ni volúmenes:

| Entorno | Proyecto | Dashboard | PostgreSQL | Persistencia |
|---|---|---|---|---|
| Desarrollo | `home-lab-dev` | `127.0.0.1:8502` | `127.0.0.1:5432` | volumen `home-lab-dev-postgres-data` y `./data` |
| Producción | `home-lab-prod` | `0.0.0.0:8501` | sólo red Docker interna | volumen `home-lab-prod-postgres-data` y `~/.local/share/home-lab` |

## Desarrollo

```bash
cp .env.example .env
scripts/dev-up.sh
```

`dev-up.sh` construye la imagen, espera PostgreSQL, aplica el esquema y `dbt build`,
y finalmente espera el healthcheck de Streamlit. El código de `src/` se monta en
el contenedor y Streamlit recarga los cambios.

Comandos cotidianos:

```bash
# Estado y logs
docker compose ps
docker compose logs -f dashboard

# Ejecutar tests en el virtualenv local
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/pytest

# Ejecutar una herramienta contra la base de desarrollo
docker compose run --rm tools transform

# Detener desarrollo sin borrar la base
docker compose stop
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
4. arranca el dashboard y espera su healthcheck;
5. instala un servicio systemd de usuario y un backup diario;
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
confiable. PostgreSQL no publica ningún puerto productivo.

## Operación productiva

```bash
# Estado, logs y healthchecks
systemctl --user status home-lab-production.service
~/.config/home-lab/production-compose.sh ps
~/.config/home-lab/production-compose.sh logs -f --tail=200 dashboard

# Reiniciar sólo la aplicación
~/.config/home-lab/production-compose.sh restart dashboard

# Ejecutar ingestas con los mismos datos persistentes de producción
~/.config/home-lab/production-compose.sh run --rm tools sync-gmail
~/.config/home-lab/production-compose.sh run --rm tools sync-mercadopago
~/.config/home-lab/production-compose.sh run --rm tools sync-siat-tgi

# Ver el calendario y ejecutar un backup ahora
systemctl --user list-timers home-lab-backup.timer
systemctl --user start home-lab-backup.service
```

Los secretos de Gmail deben copiarse a
`~/.config/home-lab/secrets/gmail_client_secret.json` y
`gmail_token.json`. Las demás credenciales se editan únicamente en
`~/.config/home-lab/prod.env`, cuyo modo debe permanecer en `0600`.

Cada deploy productivo:

1. toma un backup consistente si ya existe una base;
2. baja la imagen indicada por digest;
3. espera que PostgreSQL esté sano;
4. ejecuta `home-lab init-db` y `dbt build`;
5. reemplaza Streamlit y espera su healthcheck;
6. vuelve a la imagen anterior si el arranque falla.

Los logs Docker rotan a tres archivos de 10 MiB por servicio. Los backups se
validan con `pg_restore --list` y se retienen 14 días de forma predeterminada.

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

Un push a `main` publica en GHCR una imagen con SBOM y la despliega por digest, no
por una etiqueta mutable.

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

El job usa el environment de GitHub `production`, de modo que se pueden agregar
reglas de aprobación o restringir qué rama despliega sin cambiar el workflow.

## Chequeos rápidos

```bash
# Desarrollo y producción son proyectos diferentes
docker compose ls

# La base productiva no debe mostrar puertos publicados
~/.config/home-lab/production-compose.sh port postgres 5432

# Endpoint usado por Docker y CI/CD
curl --fail http://localhost:8501/_stcore/health
```
