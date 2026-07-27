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
