# Integraciones

Esta guía reúne la configuración, sincronización y comportamiento de las fuentes
externas. Los secretos se guardan únicamente en `.env` o `secrets/`, ambos
excluidos de Git.

## Mercado Pago

La integración usa la API oficial de reportes de **Todas las transacciones**. No
consulta solamente ventas: el reporte incluye las operaciones aprobadas que
afectaron el dinero de la cuenta. Mercado Pago genera el reporte de manera
asíncrona; `home-lab` solicita el período, espera la tarea, descarga el resultado
y lo importa sin intervención manual.

### Obtener el Access Token

1. Ingresá a [Tus integraciones de Mercado
   Pago](https://www.mercadopago.com.ar/developers/panel/app) con la misma cuenta
   cuyos movimientos querés importar.
2. Creá una aplicación —por ejemplo, `home-lab`— o abrí una existente.
3. Entrá en **Producción > Credenciales de producción**. Si todavía no están
   activas, Mercado Pago solicitará rubro, sitio web, aceptación de términos y
   reCAPTCHA.
4. Copiá únicamente el **Access Token** de producción, que comienza normalmente
   con `APP_USR-`. No hace falta usar la Public Key, Client ID ni Client Secret.
5. Guardalo en el `.env` local:

   ```dotenv
   MERCADOPAGO_ACCESS_TOKEN=APP_USR-tu-token-real
   ```

El token es una clave privada con acceso a información de la cuenta: no debe
pegarse en el código, la documentación, una captura ni un commit. Puede renovarse
desde el mismo panel si alguna vez queda expuesto.

La primera vez, configurá las columnas estables que necesita el importador:

```bash
.venv/bin/home-lab configure-mercadopago
```

Este comando crea o actualiza la configuración compartida del reporte en Mercado
Pago —columnas, separador, idioma y zona horaria—, pero no activa una programación
en sus servidores.

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

Repetir exactamente el mismo período reemplaza su lote anterior. Los lotes API
se guardan en `bronze.mercadopago_api_movements`. Los períodos superpuestos se
desduplican en Silver por ID de operación y, cuando el ID no está disponible,
por la firma y ocurrencia de la fila.

El formato oficial no incluye el saldo acumulado de cada fila, por lo que
`running_balance` queda vacío para registros obtenidos por API. Ingresos,
egresos, flujo neto, categorías y conciliación siguen disponibles.

### Importar un resumen de cuenta

El resumen descargado manualmente se trata como un documento financiero cerrado,
no como otro lote API:

```bash
.venv/bin/home-lab import-account-statement data/raw/account_statement.csv
.venv/bin/home-lab transform
```

También se puede cargar desde **Operaciones > Importar extracto de Mercado
Pago** en el dashboard. La pantalla ejecuta ambos pasos y requiere la clave de
operaciones.

El CSV original se conserva por contenido en
`data/bronze/financial-statements/mercadopago/<año>/<mes>/`. Su metadata, período,
saldos y hash quedan en `bronze.financial_statements`, y sus movimientos en
`bronze.mercadopago_statement_movements`.

Antes de persistirlo se valida que:

- créditos y débitos coincidan con el encabezado;
- saldo inicial más movimientos sea igual al saldo final;
- cada movimiento reconcilie con su saldo acumulado.

Si todos los movimientos pertenecen al mismo mes, la cobertura se expande al mes
calendario completo. Dentro de esa cobertura Silver usa exclusivamente el
statement manual, que aporta las descripciones y saldos definitivos. Las filas
API se mantienen intactas en Bronze para auditoría, pero no aparecen duplicadas
en Gold. Fuera de los períodos cerrados por statements, la API sigue aportando
los movimientos más recientes.

La ubicación de los documentos puede cambiarse con:

```dotenv
FINANCIAL_STATEMENT_STORE_PATH=/ruta/privada/financial-statements
```

Al inicializar una instalación existente, los lotes previos del esquema legado
`raw` se copian sin eliminar el origen. Silver continúa leyendo la tabla
histórica `bronze.mercadopago_account_statements` hasta que sus statements se
vuelvan a importar como documentos.

## Gmail

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

El filtro predeterminado se configura en `.env`. Incluye adjuntos PDF de Zeta,
facturas enlazadas de EPE, Aguas Santafesinas y Litoral Gas, resúmenes de
Naranja X y avisos mensuales de IPLAN:

```dotenv
GMAIL_QUERY={from:no_reply@zetace.com.ar from:oficinavirtual@epe.santafe.gov.ar from:facturadigital@aguassantafesinas.com from:factura@digital.litoralgas.com.ar from:avisos@info.naranjax.com from:noreply@iplan.com.ar} newer_than:45d
```

Para ejecutar el flujo completo:

```bash
.venv/bin/home-lab sync-gmail
```

El comando descarga adjuntos nuevos, procesa documentos pendientes y ejecuta
`dbt build`. Es idempotente: repetirlo no duplica correos ni PDF.

El script para automatización usa `flock` e impide ejecuciones superpuestas:

```bash
scripts/sync-gmail.sh
```

Ejemplo de cron diario a las 07:15:

```cron
15 7 * * * /home/emiliano/home-lab/scripts/sync-gmail.sh >> /home/emiliano/home-lab/data/gmail-sync.log 2>&1
```

## Fuentes documentales

### Expensas Zeta

El parser `zetace_expenses` extrae:

- consorcio, unidad, período y fecha de emisión;
- primer y segundo vencimiento con sus importes;
- expensas generales y extraordinarias;
- saldo anterior y cobranzas.

Cada resultado conserva nombre y versión del parser. Sus estados posibles son
`parsed`, `unsupported` y `failed`, lo que permite corregirlo y reprocesar sin
volver a consultar Gmail.

### EPE

Los correos de EPE no adjuntan el documento. El flujo reconoce únicamente
enlaces del endpoint oficial de facturación de EPE, normaliza su esquema a HTTPS,
valida la firma PDF y aplica el mismo límite de tamaño que a un adjunto.

El parser `epe_electricity_bill` extrae cliente, domicilio del suministro,
emisión, consumo, total y las dos cuotas con sus vencimientos. Las cuotas se
publican como vencimientos independientes para permitir su conciliación con
movimientos.

### ASSA y Litoral Gas

El flujo reconoce los botones de descarga enviados por Aguas Santafesinas y
Litoral Gas, decodifica localmente sus enlaces de seguimiento y sólo descarga
desde los endpoints de facturación permitidos.

El parser de ASSA publica las dos cuotas de la factura de agua e ignora los
reclamos de facturas vencidas; el de Litoral Gas publica su vencimiento único.
Ambos extraen cliente, período, emisión, domicilio, consumo cuando está
disponible e importe.

### IPLAN Hogar

IPLAN protege la descarga del PDF con reCAPTCHA, por lo que el flujo no intenta
automatizarla ni conservar un documento inexistente. En su lugar, reconoce el
correo mensual `Tu factura de Iplan* Hogar`, extrae período, importe y primer
vencimiento del mensaje guardado en Bronze, y publica una obligación de
`Internet` con trazabilidad al `message_id`. Los recordatorios de deuda y las
promociones no generan facturas.

Para probar o recuperar un PDF local:

```bash
.venv/bin/home-lab import-document /ruta/al/documento.pdf
```

El comando admite varios PDF, los guarda de forma content-addressed, procesa los
documentos pendientes y ejecuta `dbt build` una sola vez.

### Factura E de ARCA

Las Facturas E emitidas manualmente en ARCA se importan desde sus PDF:

```bash
.venv/bin/home-lab import-document \
  /ruta/factura-1.pdf \
  /ruta/factura-2.pdf
```

El parser `arca_export_service_invoice` acepta en este MVP comprobantes emitidos
en USD y extrae número, fecha de emisión, fecha de pago declarada, importe, tipo
de cambio, CAE y su vencimiento. El equivalente en pesos conserva la cotización
incluida en cada comprobante.

Las facturas emitidas se publican aparte de las obligaciones del hogar: emitir
una Factura E no registra un cobro.

La pantalla **Facturación E** también incluye un laboratorio de emisión mediante
Afip SDK. En esta etapa está fijado al ambiente `dev`, al CUIT compartido de
desarrollo y al servicio WSFEX: solicita un CAE de prueba, no un comprobante
fiscal válido. Los intentos se guardan en
`bronze.export_invoice_emissions`, separados de los PDF reales y de los totales
mensuales o de monotributo.

Creá un token nuevo en Afip SDK y guardalo sólo en el `.env` del entorno:

```dotenv
AFIP_SDK_ACCESS_TOKEN=token-nuevo-no-versionado
```

Si un token fue compartido por chat, correo o logs, revocalo antes de continuar.
No se guarda el token ni el ticket de acceso de ARCA en PostgreSQL. La base
conserva el borrador, el ID WSFEX, el número y el payload exacto antes de pedir
el CAE. Si la respuesta queda indeterminada por un corte de red, el dashboard
permite reenviar esa misma operación.

Para una factura de salario que repite cliente, descripción e importe, el mismo
formulario permite guardar un único perfil recurrente en Bronze. No automatiza
la emisión en calendario: fecha, pago y tipo de cambio se revisan antes de cada
solicitud.

Antes de emitir hay que obtener de WSFEX los códigos vigentes de país, CUIT del
país y unidad de medida. El formulario no los inventa ni los traduce. La
[referencia WSFEX de Afip SDK](https://afipsdk.com/docs/api-reference/web-services/wsfex/)
documenta los métodos de parámetros y autorización.

Producción, certificado propio, delegación del servicio y PDF generado quedan
fuera de este laboratorio. Habilitarlos requiere una revisión separada de
credenciales, punto de venta, reglas fiscales e idempotencia contra el CUIT
real.

### Naranja X

Los correos de Naranja X contienen un enlace al PDF en lugar de adjuntarlo. El
flujo sólo admite el endpoint oficial de resúmenes, valida que la respuesta sea
un PDF y aplica el límite de tamaño configurado.

El parser extrae cierre, vencimiento, total en pesos y dólares, entrega mínima y
cada consumo o cargo con fecha, tarjeta, cupón, plan, moneda e importe. El resumen
se publica como obligación y los consumos en `gold.credit_card_expenses`. Estos
últimos se muestran separados de `gold.movements` para no duplicar el gasto
cuando posteriormente se paga el resumen.

## TGI de Rosario

SIAT no ofrece una API pública, pero su gestión con código personal funciona con
un flujo HTTP estable y no requiere un navegador ni CAPTCHA. La integración
inicia una sesión anónima, descubre los períodos seleccionables y descarga cada
boleta mensual desde el endpoint oficial. Las boletas se deduplican por cuenta y
período.

Guardá el número de cuenta y el código de gestión personal únicamente en `.env`:

```dotenv
SIAT_TGI_ACCOUNT=tu-numero-de-cuenta
SIAT_TGI_MANAGEMENT_CODE=tu-codigo-de-gestion
```

Para descargar boletas nuevas, procesarlas y reconstruir Silver/Gold:

```bash
.venv/bin/home-lab sync-siat-tgi
```

El script de automatización usa `flock`:

```bash
scripts/sync-siat-tgi.sh
```

Ejemplo semanal, los lunes a las 07:30:

```cron
30 7 * * 1 /home/emiliano/home-lab/scripts/sync-siat-tgi.sh >> /home/emiliano/home-lab/data/siat-tgi-sync.log 2>&1
```

El parser `rosario_tgi_bill` extrae cuenta, inmueble, período, emisión,
vencimiento e importe. La cuenta y el código son secretos locales y nunca se
escriben en logs ni en metadatos de ingesta.

## Lecturas relacionadas

- [Arquitectura](architecture.md)
- [Modelo de datos](data-model.md)
- [Dashboard](dashboard.md)
- [Operación de desarrollo y producción](operations.md)
