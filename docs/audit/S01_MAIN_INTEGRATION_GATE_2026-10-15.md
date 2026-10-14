# S01 — Integración única a `main`: lista de verificación y bloqueo productivo

**Preparación:** 15 de octubre de 2026. **Estado: DRAFT / NO-GO a producción.**
**PR canónica:** #90 `security/s01-closeout-integration-lab-readonly`, derivada funcionalmente de #58.
**Base auditada:** `main@56882073295faae3bd1bc3632288a970acb330da`; cabeza funcional previa `4d0ef32016ce7e00b2ec3996483ec5815e29bde7`.
**Alcance acumulado a la base:** en la revisión de retarget a `main`: 91 commits / 0 detrás y 89 archivos distintos; recalcúlese en cada nuevo SHA.
**No confundir:** PR #90 contiene evidencias de seguridad y test además de cambios de producto y tres migraciones.
**Lo único aprobado hasta la fecha:** pruebas en laboratorio aislado; no aprobados merge, DDL productivo, despliegue o activación de cobros/correos de asesoramiento.

## Canonicalización ejecutada (sin merge)

- La **PR #90** pasó de base #58 a base **`main`** conservando el estado **DRAFT**. No se cambió ni un byte de `main` o Railway por esta operación.
- Este ajuste convierte un árbol de PR encadenadas en **una única PR de revisión final**. Los otros 61 PR permanecen abiertos únicamente como historial técnico; no autoriza fusionarlos, cerrarlos ni descartar pruebas.
- El siguiente commit es **sólo de documentación** para activar los controles de PR contra `main` (evento `synchronize`): no cambia la aplicación ni las migraciones. Un resultado verde de CI seguirá siendo insuficiente para autorizar el merge mientras no pasen B/C/D.
- La consulta de reglas de protección de `main` mediante la integración GitHub respondió **403**; no dar por supuestas restricciones de rama adicionales a las que podamos observar.
- **Prohibición vigente:** ninguna operación DDL, restauración, despliegue, cambio de variables o merge a la rama productiva.

## Hechos probados y límites

1. `main` es exactamente la versión que sirve Railway producción (despliegue `885a327c-a4d4-4b55-bf7b-b899c9595fdb`); la app está **conectada a la rama main** y puede desplegarse automáticamente cuando se fusiona. Nunca usar Merge como «simple cierre administrativo».
2. Staging actual despliega una rama distinta `security/staging-preflight-isolation-20261012` (deploy `6ce19749-1e4c-47c3-9efb-2319ae6b6011`), no la candidata; los ensayos sintéticos no certifican paridad con staging real.
3. La web LAB privada está online con **otro SHA**, `446470e121d66f240d1ea75a8c0e103e193d13c2`; sólo `GET/HEAD /healthz`. QA efímera Railway: `9b5b98b3-bacc-41d2-a57b-aed1308adfec` PASS sobre la cabeza previa `4d0ef320...`, con PostgreSQL 18 local a su contenedor y sin cliente real. Su autorización de repetición se revocó; ningún DDL se ejecutó en Postgres-Im3h.
4. CI previa sobre el SHA funcional anterior: `38646657401`, **4/4 SUCCESS**, 1.905 Python pass/63 omitidas, PG18 sintético, Chromium y ejecución en contenedor PostgreSQL 18 con CSV inventado y bloqueos financieros. **Exigir repetir CI sobre cada nuevo SHA.**
5. `Procfile` cambia de `python bootstrap_db.py && gunicorn` a `python startup_schema_gate.py && gunicorn`. El primero puede migrar una base durante el arranque; el segundo **inspecciona sin DDL y bloquea la web** si la revisión real no es EXACTAMENTE `z9a0b1c2d3e4` o faltan tablas, columnas, constraints o índices. El head histórico esperado antes de S01 es `v5w6x7y8z9a0`, **no verificado de nuevo sobre producción viva**.
6. El DAG elegido es **lineal**: `v5w6x7y8z9a0 → x7y8z9a0b1c2 → y8z9a0b1c2d3 → z9a0b1c2d3e4`. No fusionar U04 #29 (`w6x7y8z9a0b1`) ni la alternativa Connect #54 (reparto antiguo 50/50); tampoco importar ejecutores SQL/restore #59–#89.
7. Los endpoints de asesoramiento PayPal quedan inertes; presupuestos, links y operaciones financieras S01 siguen **HTTP 503** y el historial PayPal se conserva. Stripe (incluidos webhook/eventos de QA sintética) **no se activa para cobros reales**, independientemente de claves que aún existan en Railway. Las operaciones habituales de login/FIFO y emails no relacionados con pagos NO se deben considerar deshabilitados globalmente. Cambios de frontend de asesoramiento son **visibles** y exigen aceptación de producto previa.
8. Se han identificado en producción nombres de variables `DATABASE_URL`, `SECRET_KEY`, `PAYPAL_*`, `STRIPE_*` y `RESEND_API_KEY`; se preservan sin leer/exponer valores. **No** eliminar, rotar ni modificar variables productivas durante esta preparación.
9. El historial documenta un ensayo antiguo desde copia real del Mac Mini; hubo fallos intermedios del nuevo gate G04 y cambios posteriores de código. **No se ha acreditado en esta revisión una repetición íntegra, reciente y PASS del flujo definitivo G04 sobre un backup productivo actual**. Las pruebas de laboratorio con datos ficticios no acreditan una restauración con integridad de datos reales.

## Plan de integración sin cambios destructivos

### Puerta A — Preintegración de código (sin riesgo de servicio)
- Usar **una única PR canónica #90 en DRAFT con base main**, en vez de fusionar 61 PR históricas o crear nuevas cadenas. No rebase ni cherry-pick de U04 o Connect antiguo.
- Revisar diff total (88 archivos, cambios visibles en cinco pantallas y app.py), matriz de rutas públicas y protección de contraseñas/Google OAuth/FIFO/Modelo 721.
- Ejecutar `Required CI` al retargetar la PR contra `main`, además del QA sintético completo; exigir SUCCESS sobre HEAD final, revisar las 63 omisiones y advertencias relevantes.
- No cerrar ramas/PR históricas hasta que la integración esté aprobada y no haya pérdida de evidencia. Mantener PR #90 en DRAFT / NO MERGE mientras resten puertas.

### Puerta B — Solo lectura de producción (requiere alcance de acceso autorizado)
- Confirmar **por consulta PostgreSQL de solo lectura, sin copiar filas de clientes ni secretos**: clúster, `alembic_version`, heads, tablas S01 existentes, columnas/constraints y migraciones divergentes, estado de PostgreSQL 18, bloqueo/no pagos en curso y trabajos/cron.
- Hacer inventario cuantitativo sin PII de datos/historial PayPal que debe preservarse y de solicitudes de asesoramiento activas; NO conciliar proveedores ni hacer pagos.
- Verificar que el hash de backup y la fecha corresponden a una copia íntegra, reciente, cifrada y recuperable (no divulgar dump/hash/DSN).

### Puerta C — Ensayo completo con copia REAL aislada (sin producción)
- Operar en Mac/entorno privado sin conexiones externas: restauración de backup actual, comprobación de integridad de todas las tablas antiguas, ejecución **manual** y una sola vez de las tres migraciones S01 con el candidato exacto, verificación G04 dos veces, comparación de recuentos/huellas y conservación del historial, verificación de constraints.
- El script `tools/s01_rehearse_restored_backup.py` ya existe, pero debe revisarse para la arquitectura final (sin DDL en import/arranque) y para el SHA consolidado. **Nunca** subir backup, datos privados o trazas al repositorio, chat ni CI.
- No ejecutar `stamp` como atajo para esquemas preexistentes; abortar ante divergencia Alembic, restauración parcial o pérdida histórica. Solo una evidencia PASS del proceso actual cierra esta puerta.

### Puerta D — Preparación del corte productivo (AUTORIZACIÓN APARTE)
- Coordinar ventana de mantenimiento, backup actualizado y restauración viable, responsables, plan de reversión y revisión de protección de usuarios/ingresos. No existe rollback seguro por `downgrade`: las migraciones financieras S01 prohíben downgrades destructivos.
- Desactivar el **despliegue automático no controlado de main** o usar otro mecanismo de promoción que garantice que **la migración autorizada finaliza antes del arranque de la nueva web**; comprobar explícitamente cómo Railway aplica un merge.
- Congelar escrituras y procesos susceptibles de cobrar/crear presupuestos durante migración; gestionar webs, cola, cron y consultas; comprobar pre y post con transacción de solo lectura.
- Requerir **autorizaciones independientes** para: 1) operación administrativa DDL en PostgreSQL producción, 2) merge a main, 3) promoción/despliegue/ventana. El orden exacto depende de cómo se desacople el autodeploy; **no** dar autorización única implícita.
- Plan de reversión **demostrado** que no borre historia ni confunda registros generados entre versiones; si falla G04, no forzar rollback DDL ni restaurar a ciegas una copia antigua sobre datos nuevos. Declarar NO-GO y mantener servicio estable.

### Puerta E — Verificación tras despliegue (AUTORIZACIÓN APARTE)
- Healthz, rutas anonimizadas, login/Google OAuth de prueba controlada, generación FIFO con fichero sintético, PDF, Modelo 721, responsive, roles, asesoramiento sin presupuestos/pagos, proveedor egress y estado de mensajes, logs sin secretos y métricas 5xx.
- Confirmar bandera de suspensión de asesoramiento y estado financiero. **No activar** Stripe, PayPal, cobros, campañas o correo especial sin aprobación propia.
- Solo cuando todo pase: fusionar/cerrar PR históricas de forma trazable, proteger SHA final de main y declarar el área S01 cerrada antes de arrancar el rediseño UX/UI.

## Dictamen actual
**Código listo para revisión de integración; NO-GO a DDL, merge o producción.**
**Bloqueos principales:** revisión de diff acumulado y PASS de CI sobre PR contra main; versión real del esquema productivo sin consultar; copia íntegra reciente y ensayo completo G04 en datos históricos; plan de corte sin autodeploy intempestivo; aceptación expresa de cambios públicos.
