# S01-G05 — Contraste verificable de PayPal con la base actual (fase R02)

**13/10/2026 · SOLO preparación documental y lector de CSV local · DRAFT · NO MERGE · NO DEPLOY · NO PAYMENTS.**

## 1. Punto de partida y dictamen

- Inventario local R01 comunicado por el propietario el **13/10/2026**, sobre el respaldo original de **10/10/2026**: `expedientes_totales=6`, `expedientes_senal_paypal=0`, todos los demás indicadores financieros y anomalías definidos en R01 también `0`; `S01 R01: PASS LOCAL`.
- **No se acredita ausencia de órdenes o capturas en el proveedor**, ni de operaciones posteriores a la fecha del respaldo, borradas antes de él, pertenecientes a otra cuenta o con confirmaciones/ACK perdidos.
- **G05 sigue ABIERTO.** El instrumento nuevo examina el reporte del proveedor *fuera de línea* y su salida contiene solo contadores. No conecta a PayPal ni certifica que el reporte sea completo o esté referido a S01.
- Código base: PR #47 SHA `5fd969ca371627c2dece157ec05156957adbf3ee`. PR #29 de conciliación U04 y #30 PREFREEZE sin cambios. Árbol S01 no integrado en `main`.

## 2. Dos fuentes independientes, cuatro cortes

El dictamen G05 exige documentar **por separado**:

| Fuente | Evidencia mínima | Riesgo cubierto | Limitación |
| --- | --- | --- | --- |
| **B0: respaldo histórico** | Fecha/hora del `pg_dump`, SHA-256 del dump privado y recuentos R01; ya revisado (10/10). | Estado almacenado en la copia original | No prueba actividad externa o posterior |
| **B1: base actual** | Nueva extracción, cuando se autorice, **de solo lectura** desde producción a un dump cifrado privado o resumen de conteos, con instante UTC y esquema/Alembic anotados | Cambios en expedientes desde B0 | Ni un dump nuevo prueba estado real de PayPal; una actualización puede no guardar el ACK |
| **P0: PayPal Sandbox** | Cuentas utilizadas, periodo completo, actividad, órdenes/autorizaciones pendientes, capturas, reembolsos, disputas, eventos/webhooks y confirmación de entorno | Riesgos de pruebas mezcladas con Live | Transacciones Sandbox no representan dinero Live |
| **P1: PayPal Live** | Misma cobertura, archivos de actividad y fuentes independientes de saldos/refunds/disputes, conciliación de capturas sin ACK, cierre por fecha y revisor | Cobros reales omitidos por la BD | Un reporte filtrado/incompleto o extracto sin pendientes no prueba cero |

**Fechas:** el inicio debe cubrir desde el primer momento en que estuvo accesible el flujo PayPal legacy y cualquier periodo de pruebas con órdenes reales hasta el momento actual de revisión. El final debe ser posterior al corte operativo probado; si no se conoce ese corte, dejarlo **NO VERIFICADO**. No fijar una fecha inicial o zona horaria por suposición. Conciliar en UTC los cortes y conservar el huso horario indicado por PayPal en el documento original.

## 3. Procedimiento PayPal oficial, sin enviar datos a ChatGPT

A realizar manualmente por el **titular autorizado**, sin delegar credenciales:

1. Abrir la cuenta merchant correcta en [PayPal](https://www.paypal.com/), revisar si se utilizó otra cuenta y distinguir **Live** de **Sandbox** antes de exportar. Anotar la cobertura internamente con una etiqueta neutra, no correos ni merchant IDs.
2. Según la ayuda española de PayPal, acceder a **Historial → Descargar → Personalizar**, seleccionar el informe **Activity Download / actividad de transacciones**, periodo y formato **CSV**. Consultar [Ayuda PayPal ES](https://securepayments.paypal.com/es/cshelp/article/%C2%BFc%C3%B3mo-puedo-consultar-y-descargar-mis-extractos-e-informes-help145) y [Activity Download](https://developer.paypal.com/reports/activity-download/).
3. Los informes Activity Download permiten hasta **7 años de historial** con **12 meses máximo por informe**. **No** interpretar ausencia de filas como ausencia de pagos si faltan años o fragmentos, otras cuentas, un reporte truncado o filtros activos. En caso necesario, descargar múltiples periodos **sin solapamiento de fechas ni huecos** y verificar que se han incluido todos los fragmentos.
4. En la configuración de campos, incluir explícitamente los nombres requeridos por nuestro lector: `Date`, `Time`, `TimeZone`, `Type`, `Status`, `Currency`, `Gross`, `Fee`, `Net`, `Transaction ID`, `Reference Txn ID`, `Balance Impact`, `Transaction Event Code`. Los dos últimos pueden necesitar selección manual. El script deniega informes incompletos en vez de inventar campos. Los importes y IDs *se leen en memoria*, pero **no se devuelven**.
5. Conservar archivos originales solo en un directorio **fuera del repositorio**, privado (0700), y archivos **0600**. No abrirlos/guardarlos en hojas de cálculo en la nube, subirlos a GitHub, ChatGPT ni copiarlos al directorio de trabajo. No reenviar capturas de pantalla del Dashboard.
6. Si hay movimientos, compararlos **privadamente** contra expedientes y estado del proveedor de forma individual por el responsable financiero; nuestro resumen no permite asociar movimientos a un expediente. Un PayPal con uso ajeno al asesoramiento puede registrar movimientos no S01: **no imputarlos automáticamente**.
7. Obtener separadamente la situación actual de **órdenes/autorizaciones no capturadas**, capturas, refunds, disputas, reservas y reintentos de webhooks mediante los apartados oficiales de PayPal; la exportación Activity Download y los extractos bancarios son insuficientes por sí solos. Guardar evidencia auditada privada de revisiones y discrepancias. No crear, capturar, anular, reembolsar ni reenviar eventos.

**Motivo:** según PayPal, los [extractos mensuales](https://developer.paypal.com/reports/monthly-custom-statements/) solo contienen movimientos que afectan al saldo; no incluyen las autorizaciones sin capturar, los eChecks pendientes ni disputas no resueltas. Los informes de actividad proporcionan mayor detalle, pero tampoco sustituyen una consulta del estado actualizado de cada objeto potencialmente incierto.

### Lector local CSV — preparado, NO ejecutado en datos reales

`fiscal_app_export/tools/s01_paypal_activity_csv_offline.py` es autónomo, usa **solo la biblioteca estándar de Python** y no tiene importaciones de `app.py`, SDK PayPal, Stripe, PostgreSQL ni red. Puede ejecutarse en macOS después de revisar el commit y pasar la CI; nunca en GitHub Actions con datos privados.

- Rechaza archivo inexistente, symlink, fuera de formato CSV, con permisos abiertos, de otro usuario, dentro del repositorio, de más de 64 MiB o con más de 50.000 filas. Exige cabeceras mínimas documentadas, UTF-8 y columnas estructuralmente válidas.
- Cuenta filas, IDs distintos, IDs vacíos, grupos de IDs repetidos, estados de actividad, impactos Credit/Debit/Memo, EUR vs otras divisas, T-codes con formato reconocido y filas con referencia parent, **sin imprimir ninguna fila ni valor procedente del CSV**.
- Un mismo Transaction ID repetido **no implica** un segundo cargo, y `estado_completed` **no significa** necesariamente una captura S01. `filas=0` **no cierra G05**. Los T-codes de formato válido no se interpretan como prueba de cobro.
- El propio lector no verifica la cobertura temporal, cuenta merchant, si hubo filtros, si el informe fue manipulado, datos fuera de fechas, qué actividad corresponde a S01 ni discrepancias de saldos. **Todas estas verificaciones son manuales e independientes.**
- En caso de NO-GO del lector, no copiar logs ni abrir el fichero a través del chat; ajustar descarga/columnas bajo supervisión.

**Ejecución posterior solo si se ha comprobado la CI y el SHA exacto.** Como el nombre real del CSV no se conoce, no hay comando que asuma una ruta inventada:

```bash
cd "$HOME/s01-paypal-provider-source"
test "$(git rev-parse HEAD)" = "<SHA_CERTIFICADO_DE_LA_PR>"
PYTHON="$HOME/s01-rehearsal-source/.venv/bin/python"
CSV="/RUTA/ABSOLUTA/PRIVADA/al-informe-exportado.csv"

"$PYTHON" fiscal_app_export/tools/s01_paypal_activity_csv_offline.py --csv "$CSV"
```

Si se compartiesen resultados, **solo** las líneas `S01 G05` con recuentos, nunca nombre real de fichero, merchant ID, encabezados, valores de muestra, transaction IDs, CSV, importes, email, fechas detalladas ni balances. El responsable autorizado debe conservar confidencialmente las evidencias originales en el Mac bajo sus políticas de retención.

## 4. Base de datos actual B1 — preparación, sin conexiones productivas

No se conecta ahora a Railway. Una autorización futura deberá precisar: usuario que lee, rango de datos, fecha UTC de corte, método, límites de tiempo/red, aprobación para crear una copia cifrada y su eliminación controlada, revisión de acceso y **ausencia de escrituras**. Preferir crear una nueva copia privada cifrada con integridad comprobada; después ejecutar el **inventario R01** sobre una restauración aislada en Mac mini, **solo si el esquema y la revisión Alembic se mantienen compatibles** (el R01 actual exige el head histórico `v5w6x7y8z9a0`). No alterar ese guard para forzar la ejecución.

Un backup *no es* un permiso para habilitar cobros ni sustituye la evidencia de PayPal. Las lecturas en SQL de producción, aunque sean `SELECT`, requieren autorización expresa por trabajar con datos sensibles. No se deben compartir DSN, contraseñas, dumps, hashes de datos, nombres o capturas de sistemas internos.

## 5. Acta de conciliación — modelo seguro

El responsable revisará y conservará un acta **privada** con:

| Campo | Ejemplo de formato; nunca inventar valores |
| --- | --- |
| Fecha/hora de corte | ISO UTC; sin asumir hora del backup |
| Cuenta y entorno | Etiqueta interna local, Live/Sandbox |
| Intervalo cubierto y huecos | Desde/hasta UTC, filtros, informes fragmentados |
| Evidencia B0/B1 | R01 por copia, hashes bajo custodia privada |
| Evidencia PayPal | Activity Download, autorizaciones pendientes, capturas, refund/dispute, ledger/saldo |
| Clasificación financiera | Coincidencias, pendientes, divergencias, casos no atribuibles a S01 |
| Decisiones de retención | Bloqueo por expediente y justificación auditada, sin mover dinero |
| Revisor y segundo control | Responsable humano, fecha y evidencia de revisión |
| Dictamen | **PASS / NO-GO / INCONCLUSO**, nunca deducido automáticamente |

**Cierre de G05:** revisar todas las cuentas pertinentes y ventanas completas, obtener estado proveedor contemporáneo y cifras actuales de BD, resolver discrepancias o mantenerlas formalmente en cuarentena sin permitir nuevos cargos, validar reembolsos/disputas y emitir un acta de control humano revisable. Hasta entonces G05 **ABIERTO**, sin que cero en B0 o cero en un CSV parcial alteren ese dictamen.

## 6. Alcance de la PR

Código de lectura **solo offline**, pruebas sintéticas, documentación; sin alteración de app Flask, modelos, migraciones, Procfile, Railway, Stripe, PayPal, MERU o ficheros privados. Sin merges, desplegar, crear órdenes, capturar, reembolsar, enviar correos ni emitir facturas. Rafa continúa gestionando la facturación fuera de la aplicación.

### Documentación de PayPal contrastada

- [Ayuda ES — descargar extractos e informes](https://securepayments.paypal.com/es/cshelp/article/%C2%BFc%C3%B3mo-puedo-consultar-y-descargar-mis-extractos-e-informes-help145)
- [Activity Download report — campos, periodos y estados](https://developer.paypal.com/reports/activity-download/) (actualización oficial 02/07/2026)
- [Monthly and custom statements — movimientos que afectan al saldo](https://developer.paypal.com/reports/monthly-custom-statements/) (actualización oficial 21/07/2026)
- [PayPal Balance Report — pagos, devoluciones, disputas, fees](https://developer.paypal.com/reports/financial-reports/balance-report/)
