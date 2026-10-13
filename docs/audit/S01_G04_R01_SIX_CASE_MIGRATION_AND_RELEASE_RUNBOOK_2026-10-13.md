# marianosevilla.com — G04-R01 · Preparación del corte S01 y recuperación segura

**13/10/2026 · PLAN Y ENSAYOS SINTÉTICOS · NO EJECUTAR EN PRODUCCIÓN.**
Sin cambios Railway, migraciones de producción, backups nuevos, merges, pagos ni secretos. Este runbook NO otorga ninguna autorización operativa. Proyecto: `MarianoSevilla/fiscal-cripto-`.

## 1. Estado verificado de producción y límite G05

- GitHub `main` y último despliegue web Railway `SUCCESS` apuntan a **`56882073295faae3bd1bc3632288a970acb330da`** (11/10/2026). Versión candidata revisada C2-R02: **`74bea12848aa53e05a653cec8802a7b675819da0`** (PR #58; ninguna integración efectuada).
- Alembic **real** de producción, consultado directamente por el propietario en el editor SQL: **`v5w6x7y8z9a0`**. No equivale a una migración pendiente ya aplicada.
- Contadores reales de 6 solicitudes: PayPal órdenes 0/capturas 0; Stripe sesiones 0/intents 0; indicios de presupuesto 1; aceptaciones 0; token de enlace 1; indicios de pago 0. La segunda consulta real: **1** token en estado `quote_sent`, **0** potencialmente vigente en el instante de consulta. Son indicios locales, **NO una conciliación del proveedor PayPal**.
- Railway producción: web y PostgreSQL 18 online; web 1.198 HTTP en 24 h, 0 respuestas 5xx; PostgreSQL tenía 2 avisos no críticos sin clasificar. Staging usa su propio servicio y volumen DB. **No están verificados los valores reales del enlace DATABASE_URL ni el control de auto-deploy**; la configuración de aplicación de producción usa `main`.
- Las variables PayPal existen **por nombre**, no se han leído ni inferido sus valores. La web del SHA desplegado conserva `/api/pago/iniciar/<token>`, `/api/pago/paypal/capture`, `/api/admin/asesoramiento/solicitudes/<id>/enviar-presupuesto`. El único token pendiente estaba caducado, pero no equivale a PayPal desactivado. Mantener advertencia de no repetir pagos.
- Producción `Procfile` del SHA viejo: `python bootstrap_db.py && gunicorn ...`; **candidato**: `python startup_schema_gate.py && gunicorn ...`, con gate de **solo lectura** y exigencia de head exacto `z9a0b1c2d3e4`. No dejar código nuevo arrancar en esquema viejo; tampoco reiniciar inadvertidamente código viejo cuando BD ya está en esquema nuevo.

## 2. Tres revisiones Alembic aprobadas para ensayo

1. `x7y8z9a0b1c2` (parent `v5w6x7y8z9a0`): añade `rafa_fee_cents`, `commission_cents` y `commission_rate_bps` como NULL por defecto. Sin recomputar importes históricos.
2. `y8z9a0b1c2d3`: crea `s01_stripe_checkout_attempts` y `s01_stripe_event_receipts`, claves foráneas, índices y CHECK explícitos.
3. `z9a0b1c2d3e4`: crea `s01_stripe_notification_outbox`, sin generar mensajes ni emails retroactivos. Mantener tablas vacías, no establecer comisiones hipotéticas.

**Prohibido agregar `w6x7y8z9a0b1` de PR #29 (U04 PayPal); PR #54 Connect 50/50 está descartada.** No hacer `alembic stamp` directo a head; no reemitir presupuestos, importar backfills ni borrar expedientes.

## 3. Evidencia que existe y ensayo adicional

- [Required CI #87](https://github.com/MarianoSevilla/fiscal-cripto-/actions/runs/38418190182): backend 1.556 passed, 63 skipped; PG18 de integridad, race C2-R01, import sin DDL, rechazo de head antiguo y gate READ ONLY; 26 comprobaciones E2E de navegador C1.
- `tests/qa_s01_paypal_retirement_pg18.py`: ejecuta el DDL real de las tres migraciones contra una tabla de historial simplificada con orden/captura sintética y verifica su retención.
- `tools/s01_rehearse_restored_backup.py`: dispone de restauración privada **sin TCP** en Mac de una copia real y doble ejecución de `bootstrap_db.py`; valida huellas de todas las filas históricas, CHECKs, índices, head y arranque read-only sin subir datos. La PR #49 contiene un segundo resultado **PASS reportado por el propietario**, no una nueva restauración del día de hoy.
- `tests/qa_s01_g04_six_legacy_pg18.py`: **nuevo ensayo CI** para exactamente seis expedientes ficticios, uno `quote_sent` con token ya caducado y ninguno con evidencias de pago. Ejecuta el DDL idéntico de los tres scripts en PG18 efímero, compara todos los campos anteriores, once conteos agregados, nuevas columnas NULL, nuevas tablas vacías, índices/CHECKs y head final. **NO contiene copia de usuarios ni token real.**
- El PG18 sintético de CI **no sustituye** la restauración privada y verificación de un backup de producción fresco. Las migraciones del test no se ejecutan sobre Railway.

## 4. Orden de operaciones futuras, supeditadas a nueva autorización

**A. Congelación:** verificar SHA de `main` y head candidato, dependencias lineales (82 commits desde main en #58), protección de rama y auto-deploy real. Poner un gate efectivo sobre deploy automático **antes de fusionar**. Mantener afuera #29, #54 y ramas laterales. Documentar ventana y responsables.

**B. Cierre operativo G05:** revisar los seis conteos y la no vigencia del token ya contrastados; si PayPal pudiera recibir nuevas órdenes por otras vías, planificar contención operativa separada. No modificar el token ni expediente histórico; si aparecen señales nuevas se amplía la conciliación solo de lo imprescindible.

**C. Rehearsal con copia fresca:** generar bajo autorización y custodia segura un backup cifrado completo verificable, conservando retención y acceso restringido. Restaurar fuera de Railway production, comparar versión inicial `v5w6x7y8z9a0`, ejecutar de forma aislada el flujo real con la herramienta offline privada; confirmar literalmente `z9a0b1c2d3e4`, inventario de tablas, índices, CHECKs, huellas sin pérdida, 6+ registros reales y no backfills. No publicar hashes de contenido de clientes, logs, URLs DB, tokens ni dumps.

**D. Staging:** autorizar por separado un entorno de aplicación/candidato en staging con base sintética/restore desidentificado y **ningún proveedor real**. Ejecutar el bootstrap explícito de mantenimiento en la base de staging primero; gate G04; E2E login/FIFO/intake/gestión interna, 503 financieros; comprobar salida de correos y proveedores deshabilitada. Ensayar recuperación ante fallo entre migración y reemplazo web.

**E. Ventana de producción (NO AUTORIZADA):**
1. Antes de nada garantizar corte o contención del tráfico y de los procesos antiguos **sin recuperar PayPal**, incluidos workers y redirecciones/webhooks. Debe contemplarse que el `Procfile` viejo **migra automáticamente al arrancar**, por lo que un reinicio de la versión vieja tras un upgrade de DB puede romper el servicio.
2. Confirmar respaldo fresco y restaurable, revisión Alembic exacta `v5w6x7y8z9a0`, integridad/footprint S01, controles del disparador de Railway y capacidad de desplegar nueva imagen exacta. STOP si no hay ventana de mantenimiento y rollback seguro.
3. Ejecutar solo bajo autorización explícita la actualización Alembic administrativa de **las tres revisiones** utilizando el comando del release candidato `bootstrap_db.py`, nunca la web/Procfile. Guardar evidencia no sensible de ejecución; no hacer stamp manual.
4. Validar inmediatamente revision exacta, columnas, constraints/indexes y que el historial sigue íntegro. Ante anomalía, STOP: no arrancar nueva web.
5. Poner en servicio el SHA previamente aprobado **sin activar cobros**; confirmar que `startup_schema_gate.py` PASS con transacción READ ONLY, web + procesos auxiliares + FIFO correctos, rutas financieras 503. Vigilar 5xx **excluyendo los 503 deliberados de mantenimiento financiero** para análisis de disponibilidad; registrar ambos tipos separados.
6. Levantar contención solo después de validación formal. Documentar el SHA final tanto de la app como de la base y comunicar estado de S01 al soporte.

**F. Rollback/contingencia:** prohibido degradar en caliente a la web antigua que contiene PayPal, ejecutar `alembic downgrade` (los nuevos módulos lo prohíben), restaurar un dump viejo borrando solicitudes nuevas, crear otra orden de pago o limpiar filas inciertas. Ante corte fallido conservar datos y controles de pago suspendidos; recurrir a imagen de contingencia segura y compatible con head nuevo, **previamente ensayada**. Hoy **NO existe evidencia de esa imagen de contingencia ni del corte probado**: el plan NO es todavía ejecutable en producción.

## 5. Gates de salida y estado

**GO técnico limitado**: migración lineal y esquema PG18 sintéticos; comparativa de seis expedientes sin operaciones reales; segunda copia restaurada Mac reportada en #49. **NO-GO general** hasta: (i) confirmar aislamiento de variables de DB y auto-deploy; (ii) auditar alertas PostgreSQL; (iii) respaldo fresco probado; (iv) recuperar servicio con pagos bloqueados si falla el corte; (v) staging con el release exacto y el esquema migrado; (vi) autorizar por separado GitHub merge, infraestructura, migración y publicación.

**No ejecutar comandos de mantenimiento de la BD productiva desde este runbook sin ese GO.**
