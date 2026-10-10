# Plan de publicación controlada — responsive + bootstrap PostgreSQL

**Estado: PREPARADO, BLOQUEADO PARA PRODUCCIÓN. No ejecutar ningún merge/redeploy sin autorización nueva y explícita del propietario.**

Fecha de preparación: 2026-10-10. Proyecto: `MarianoSevilla/fiscal-cripto-`.
Rama candidata: `release/2026-10-10-responsive-postgres`.
Código desplegado y validado en staging: `9a182678bdb33ead0f18c3d0023ef7415c60a9d1`.
Commit público previo: `9716aa4a72f8a6408f596486e6bafe28be91b321`.
PRs originales en borrador (NO fusionar por separado): #18 responsive y #19 bootstrap.

## 1. Control de alcance

Únicamente cinco archivos afectan al comportamiento de la aplicación:

- `fiscal_app_export/static/nav.css`
- `fiscal_app_export/static/nav.js`
- `fiscal_app_export/static/landing.html`
- `fiscal_app_export/Procfile`
- `fiscal_app_export/bootstrap_db.py` (nuevo)

Los demás cambios son pruebas automatizadas, workflows CI y este procedimiento.
No hay modificaciones en el motor FIFO, los cálculos fiscales, los modelos, las revisiones Alembic históricas, pagos ni el backend de autorización.

## 2. Evidencia de staging (NO es evidencia de producción)

- Staging Railway: servicio `fiscal-cripto-staging` + PostgreSQL `Postgres-zZky` con volumen independiente.
- Build `db24a442-3391-4e66-90fc-9a4d82bcc935`, estado **SUCCESS**. Código `9a182678`.
- Migraciones desde baseline `m6n7o8p9q0r1` hasta head `v5w6x7y8z9a0` y arranque Gunicorn correcto.
- CI integración: https://github.com/MarianoSevilla/fiscal-cripto-/actions/runs/38086640295
  - 64 escenarios de navegación, 11 anchuras de Home.
  - Flask con sesiones ficticias: 40 HTTP/API y 29 comprobaciones en navegador.
  - Suite: 1128 passed, 63 skipped, 970 warnings.
- PostgreSQL 18 y regresión: https://github.com/MarianoSevilla/fiscal-cripto-/actions/runs/38086640298
  - Base vacía, base ya migrada con usuario de prueba, rechazo de base sin historial con datos y rechazo de esquema incompleto.
- Smoke HTTPS real: https://github.com/MarianoSevilla/fiscal-cripto-/actions/runs/38087152425
  - Home, /como-funciona y /faq HTTP 200; /api/me anónima; /stats exige login; navegador 320/375/1280.
- Validación manual de Home en móvil por propietario: satisfactoria.
- Límites: pantallas privadas no auditadas visualmente en todos sus flujos; no se ejercitaron pagos, emails ni carga de archivos reales.

## 3. BLOQUEO previo: comprobar historial Alembic de producción

**Pendiente, sin evidencia suficiente a 2026-10-10.**
La integración de Railway permite leer servicios/logs, pero no ejecutar SQL de sólo lectura en el PostgreSQL de producción.
El antiguo despliegue correcto prueba que la aplicación funciona, NO que `alembic_version` esté en head.

Comprobación manual **estrictamente de solo lectura**, desde la consola de consultas del PostgreSQL
**del entorno production**, verificando primero nombre de entorno/servicio, sin copiar credenciales aquí:

```sql
SELECT current_database() AS db_name, current_schema() AS schema_name;
SELECT to_regclass('public.alembic_version') AS version_table;
SELECT version_num FROM public.alembic_version;
```

**Único resultado aceptable para este cambio:** una fila de `alembic_version` con
`v5w6x7y8z9a0` en la base esperada. Si la tabla no existe, hay cero/múltiples revisiones,
hay revisión distinta o hay error, **DETENER**. No ejecutar `stamp`, `upgrade`,
`create_all`, DDL ni consultas con escritura para forzar el preflight. No modificar
`DATABASE_URL` de producción.

También verificar que existe una copia de seguridad reciente y un procedimiento
de restauración operativo para la base de producción, sin asumir que un rollback de
código revierte cambios de esquema.

## 4. Gate de publicación

1. Cerrar de forma explícita el bloqueo anterior y la revisión humana del diff (sobre todo `Procfile` y `bootstrap_db.py`).
2. Confirmar que `main` sigue exactamente en `9716aa4a72f8a6408f596486e6bafe28be91b321`, o revisar conflictos si avanzó.
3. Validar CI correcto sobre **HEAD exacto** de la candidata y equivalencia de los cinco archivos de aplicación con el commit ensayado en staging.
4. Confirmar ventana de baja actividad y responsables del seguimiento.
5. Obtener autorización expresa NUEVA para fusionar **una única PR candidata**.
6. Advertencia: producción Railway sigue la rama `main` y `checkSuites=false`. Un merge puede iniciar inmediatamente el despliegue; `main` no tiene protección de rama según API. No realizar merges de #18 y #19 por separado.
7. Tras aprobar, realizar un solo merge sobre `main`, esperar al deployment `SUCCESS`, cotejar SHA, consultar logs, probar GET de Home/FAQ/Cómo funciona, `/api/me`, acceso protegido y menús móvil/escritorio, sin transacciones reales.
8. Observar errores HTTP 5xx, logs, disponibilidad y métricas durante un intervalo definido por el responsable antes de declarar cierre.

## 5. Estrategia de reversión

Antes del merge, registrar IDs y SHA de despliegue y copia de seguridad:
- Deployment de producción previo: `78297669-8fde-489b-bfd9-fe18f4f9c426`.
- SHA previo en `main`: `9716aa4a72f8a6408f596486e6bafe28be91b321`.
- Railway indica `canRollback=true` para ese deployment en la inspección previa.

Si falla el despliegue o aparecen regresiones:
1. Suspender nuevas modificaciones y capturar logs/errores sin datos personales.
2. Con autorización para la reversión, restaurar el build anterior en **el servicio web de production**, nunca en PostgreSQL; Railway admite redeploy del deployment anterior.
3. Evitar que una posterior actualización de `main` relance accidentalmente el código defectuoso: preparar también revert Git del commit de integración, con control de concurrencia y autorización.
4. Si el SQL preflight no confirmó head previamente o una migración cambia datos/esquema, no afirmar que revertir la aplicación restaurará la base: usar procedimiento de recuperación verificado y criterio experto.
5. Comprobar HTTP de producción, sesiones, dashboard y logs antes de cerrar rollback.

**Nunca** borrar tablas, restablecer contraseñas de usuarios, reinicializar PostgreSQL,
reutilizar base/secret de staging o introducir datos personales reales en pruebas.

## 6. Decisión actual

**GO para preparar y ensayar en staging; NO-GO para publicación hasta verificar
la revisión Alembic de producción y backup/restore.**
