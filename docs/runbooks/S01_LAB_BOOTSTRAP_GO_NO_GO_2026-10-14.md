# S01 LAB — Runbook futuro de bootstrap con autorización (NO EJECUTAR)

Fecha de diseño 14/10/2026. **Este documento no concede permiso de escritura ni de despliegue.** El bootstrap sobre PostgreSQL Railway sigue NO-GO.

## Identidades conocidas y estado inicial
- Railway proyecto `fiscal-cripto-s01-lab`: `5f26aa6e-2e6d-46ef-bb5f-bca4ece07d5e`.
- Entorno `lab`: `3f9758ef-4e26-4e8d-9dd4-7b9286d81ea8`.
- PostgreSQL lab: `f680f3fc-4581-44ff-8bc1-d034840f2c7e`; volumen dedicado `c35d178f-7473-4d0b-adb9-1faae815b7af`.
- Web lab: `212f4f52-b349-4387-a046-9f6b08237d2e`, sin código ni despliegue.
- Maintenance lab: `9728d19b-7d17-4acb-8be1-c4b0847179df`, sin código ni despliegue; reinicio `NEVER`, sin cron ni dominio/TCP públicos.
- Última consulta del propietario STG-B09: `railway`, PG `180006`, objetos básicos en `public` a cero. **No es evidencia permanente de vacío**.

## Gate A — GitHub / cadena de dependencias
- [ ] Reconciliar las PR DRAFT #61, #62, #63, #64, #65, #66 y posteriores sin saltar ramas ni perder cambios; comprobar SHAs exactos, CI de regresión, revisiones independientes y estado del `main`.
- [ ] Preparar runner **operativo distinto** del ensayo CI (cuyo `main()` está intencionadamente cerrado); la implementación futura debe tener rutas administrativas mínimas, sin `app.py`, pagos, correo ni interfaz web.
- [ ] Revisar conjunto de modelos, seeds/migraciones `m6n7o8p9q0r1`→`z9a0b1c2d3e4`, parámetros de TLS, errores/logs, no-retry, bloqueo y postflight.

## Gate B — Railway / identidad / red
- [ ] Repetir inventario con lectura independiente: project/env/maintenance/DB ID, volúmenes y ausencia de fuente, dominios públicos, proxies TCP, cron, despliegue automático y otros procesos escritores.
- [ ] Confirmar `DATABASE_URL` configurada como referencia Railway **al Postgres de ESTE laboratorio**. Esta conexión OAuth devuelve nombres pero oculta valores efectivos; la comprobación del DSN y DNS reales **sigue pendiente**. El host `postgres.railway.internal` por sí solo no identifica el proyecto.
- [ ] Verificar valor efectivo de `RAILWAY_PRIVATE_DOMAIN` (esperado por convención `s01-lab-maintenance.railway.internal`), TLS y procedencia de conexión sin revelar credenciales en logs ni conversación.
- [ ] Inspeccionar base `railway` PostgreSQL18 con transacción READ ONLY; comprobar `public` totalmente vacío de relaciones, tipos, funciones, índices, secuencias, sin otros esquemas propios, extensiones extras ni eventos inesperados. Si un solo objeto no esperado existe, STOP.

## Gate C — Recuperación y autorización
- [ ] Preparar backup previo y **comprobar realmente una restauración en destino aislado**. Nunca asumir que una migración fallida se puede revertir mediante un comando de Alembic.
- [ ] Demostrar que no hay procesos externos escribiendo. El advisory lock solo protege a ejecutores colaboradores.
- [ ] Diseñar autorización de un solo uso vinculada a proyecto, entorno, servicio, SHA completo y propósito; sin banderas genéricas como `LAB_MODE`. Procedimiento de revocación y auditoría.
- [ ] Registrar **autorización explícita específica del propietario** para escrituras SQL únicamente en laboratorio, con alcance y ruta de recuperación acordados. Hasta entonces, NO-GO.

## Gate D — Secuencia conceptual futura
1. Lecturas del estado real y preflight inmutable; si difiere, STOP.
2. Backup/restauración validados; autorización única; proceso administrativo privado ejecutado una vez bajo SHA aprobado.
3. Validación posterior separada de esquema, revisión Alembic, constraints y `startup_schema_gate.py` READ ONLY.
4. Si falla después de un cambio, no reintentar ni reparar automáticamente. Bloquear nuevos intentos, preservar evidencia sin secretos y decidir recuperación tras inspección.
5. Retirar capacidad operativa, verificar reinicio desactivado y superficies públicas ausentes.
6. La preparación/despliegue del web en B11 requiere otra puerta de autorización: inicializar BD no autoriza publicar la web.

## Decisión a la fecha

Pruebas PostgreSQL18 sintéticas satisfacen solo un subconjunto del riesgo. Sin pruebas de identidad efectiva ni backup restaurable, **no conectar código ni permitir DDL en Railway**, no desplegar, no integrar `main`, no activar pasarelas o correo.
