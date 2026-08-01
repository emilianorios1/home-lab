# Dashboard

El dashboard Streamlit consulta los modelos Gold. Sus páginas de reporte son de
sólo lectura; la carga manual y las sincronizaciones viven en interfaces
explícitas de mantenimiento.

## Puesta en marcha

Construí Gold y levantá la aplicación:

```bash
.venv/bin/home-lab transform
docker compose up -d --build dashboard sync-runner
```

Abrí [http://localhost:8501](http://localhost:8501). Desde otro dispositivo de
la misma red local, usá `http://<ip-local-de-la-pc>:8501`.

El dashboard ofrece:

- resumen mensual de gastos compartidos;
- carga o corrección del alquiler bruto mensual;
- cálculo del alquiler neto descontando expensas extraordinarias;
- conciliación entre facturas y pagos de Mercado Pago;
- resumen y movimientos financieros;
- Facturas E del mes y acumulado móvil de 12 meses;
- laboratorio de emisión Factura E en el sandbox de Afip SDK;
- documentos y facturas;
- vencimientos e importes;
- descarga del PDF original;
- estado y errores de parsing;
- sincronización manual de Gmail, Mercado Pago y TGI.
- importación manual del extracto CSV de Mercado Pago.

El almacenamiento documental se monta como sólo lectura dentro del contenedor.

## Operaciones

La pantalla **Operaciones** permite ejecutar `sync-gmail`, `sync-mercadopago` y
`sync-siat-tgi`. Cada comando importa su fuente y reconstruye Silver/Gold. Sólo
puede ejecutarse uno por vez para evitar dos `dbt build` simultáneos.

En la misma pantalla se puede subir el CSV de **Resumen de cuenta** descargado
desde Mercado Pago. La importación valida saldos, conserva el archivo original y
reconstruye Silver/Gold. Repetir un extracto del mismo período actualiza ese
período sin duplicarlo.

La pantalla requiere `HOME_LAB_OPERATIONS_PASSWORD`. La clave desbloquea las
acciones durante la sesión actual del navegador; no se guarda en PostgreSQL. El
runner no publica puertos al host y es el único de los dos servicios que recibe
las credenciales externas, salida a Internet y escritura en `/data`.

La primera versión espera el resultado dentro de la pantalla. Si el navegador
se desconecta, el runner continúa; al intentar otra operación se informa que ya
hay una sincronización en curso. No conserva historial de ejecuciones.

## Facturación E

La pantalla **Facturación E** muestra el importe emitido durante el mes, el
acumulado móvil de 12 meses y el detalle de comprobantes. Los totales en pesos
usan el tipo de cambio guardado en cada PDF, sin recalcular facturas históricas.

El límite anual no está fijado en el código porque ARCA lo actualiza. Para ver el
porcentaje consumido y el margen disponible, configurá en `.env` el límite
vigente de tu categoría:

```dotenv
MONOTRIBUTO_ANNUAL_LIMIT_ARS=valor-vigente
```

La pantalla es un control operativo y no reemplaza la verificación del límite y
la categoría en ARCA o con un contador. Las facturas emitidas no se muestran
como cobradas hasta que exista una conciliación de ingresos en una fase futura.

Al final de la misma pantalla hay un laboratorio WSFEX fijado al ambiente de
desarrollo de Afip SDK. Requiere `AFIP_SDK_ACCESS_TOKEN`, confirmación explícita
en cada alta y los códigos oficiales de país y unidad. Cada envío es directo: no
guarda payloads, historial ni reintentos. Si la respuesta queda indeterminada,
primero verificá el sandbox antes de intentar otra emisión.

Los CAE son de prueba: se muestran al responder WSFEX, no se mezclan con los PDF
emitidos realmente, no alteran los totales y no generan un PDF fiscal válido.

Si la factura de salario repite cliente, servicio e importe, el botón
**Guardar perfil recurrente** conserva esos datos localmente. Cada mes el
formulario los precarga; sólo revisá fecha, fecha de pago y tipo de cambio antes
de confirmar la emisión de prueba.

## Gastos compartidos

El resumen mensual reúne las obligaciones del hogar y los movimientos usados
para pagarlas. Las facturas de Expensas, Luz, Agua, Gas, TGI e Internet entran
en el mes de su vencimiento. Internet se obtiene del aviso mensual de IPLAN,
porque su PDF requiere una descarga manual con reCAPTCHA. El alquiler bruto se
carga para cada mes en el dashboard y el movimiento categorizado como
`Alquiler` en Mercado Pago se usa para comprobar el pago.

La carga mensual se guarda en `bronze.manual_monthly_rents`. Corregir un importe
actualiza el mismo mes. Mientras no exista una carga explícita, el resumen
mantiene la vista histórica calculando el alquiler bruto desde el pago observado
y las expensas extraordinarias.

El cálculo conserva separadas las obligaciones y los pagos:

```text
alquiler bruto - expensas extraordinarias = alquiler efectivo
alquiler efectivo + facturas del mes      = total del hogar
total del hogar / 2                       = parte de cada persona
total del hogar - pagos conciliados       = pendiente
```

Las expensas extraordinarias se muestran para explicar el descuento aplicado al
alquiler, pero no se suman nuevamente al total. `Parte de cada persona`
representa una división en partes iguales; todavía no descuenta transferencias
entre las personas ni determina quién le debe a quién.

Cada servicio puede tener uno de estos estados:

- **Pagado**: todas sus facturas del mes tienen un movimiento conciliado.
- **Parcial**: sólo una parte de las facturas o cuotas está conciliada.
- **Pendiente**: existe la factura, pero todavía no se encontró el pago.
- **Sin factura**: aún no se importó una obligación para ese servicio y mes.

La conciliación usa las facturas importadas desde Gmail o SIAT y busca pagos
compatibles en los movimientos de Mercado Pago. Los períodos históricos que ya
no puedan descargarse pueden cargarse en `bronze.manual_shared_expenses`;
participan del mismo resumen sin guardar importes personales en el repositorio.

En la pantalla **Gastos compartidos** se puede:

- elegir el mes y ver el total, la parte de cada persona y el progreso de pago;
- cargar o corregir el alquiler bruto informado por la inmobiliaria;
- revisar el cálculo separado del alquiler;
- identificar rápidamente servicios pendientes y sus vencimientos;
- descargar el PDF de los servicios que entregan un documento automatizable;
- copiar un resumen para compartir;
- desplegar el detalle de facturas y conciliaciones.

Los PDF originales se conservan en el almacenamiento documental. Se pueden
buscar, filtrar por tipo, emisor o estado de procesamiento y descargar desde
**Documentos y facturas**.

## Validación

Después de cambios en el dashboard o sus consultas:

```bash
.venv/bin/python -m pytest tests/test_dashboard_queries.py
.venv/bin/home-lab transform
```

Cuando cambia el comportamiento visual, también hay que recorrer la página
localmente.
