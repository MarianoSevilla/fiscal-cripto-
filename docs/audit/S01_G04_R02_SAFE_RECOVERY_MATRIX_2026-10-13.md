# S01 G04-R02 — Matriz de recuperación segura y validación previa a staging

**13/10/2026. Documento y test CI aislado; NO se ha realizado despliegue, cambio de servicio/variables o ejecución de migraciones en Railway.**

## Estado y límites comprobados

- Producción Railway `fiscal-cripto-`: fuente GitHub `main` en SHA `56882073295faae3bd1bc3632288a970acb330da`; schema real `v5w6x7y8z9a0` y seis solicitudes, un token `quote_sent` **caducado**, cero referencias de captura/cobro. **No declarar cobros imposibles fuera de los registros locales.**
- Candidato S01 congelado en cabeza de PR #59 `839aafb7ef24b8265c67bc51619132c58ba3acf3` hasta este cambio, con G04 y C1/PREFREEZE. **No hay release productiva**.
- Configuración Railway de producción confirma repositorio + rama `main`; la ficha no expone prueba concluyente de un bloqueo de autodespliegue. La rama de staging sigue siendo `security/staging-preflight-isolation-20261012`. Es obligatorio resolver un mecanismo verificable de contención de despliegues **antes de un merge**.
- Se conoce el `Procfile` publicado: `python bootstrap_db.py && gunicorn ...`; el nuevo: `python startup_schema_gate.py && gunicorn ...`. Si hay rollback ciego a versión vieja, reaparecen rutas PayPal, aunque estén actualmente sin referencias activas de cobro.
- No hay evidencia de una **imagen binaria de rescate independiente** ya construida, registrada y probada. El test G04-R02 únicamente prueba la aplicación candidata **con esquema compatible** y operaciones financieras bloqueadas. Hasta disponer de contingencia probada, **NO-GO despliegue productivo**.

## Matriz de decisiones si falla el corte (simulaciones, no operaciones)

| Fase observada | Señal de STOP | Conducta segura | Acción prohibida |
|---|---|---|---|
| Antes de migración | Alembic distinto de `v5w6x7y8z9a0`, cambio en GitHub, ausencia de backup restaurable | No desplegar; dejar versión actual estable, mantener contención de cobros definida para la ventana | Avanzar o saltar `stamp` |
| Tras migración, antes de servir nueva app | Gate no pasa, faltan checks o columnas | Mantener tráfico pausado; resolver desde respaldo y procedimiento administrado o imagen de contingencia sobre head nuevo | Arrancar antiguo `Procfile` o hacer downgrade |
| Nueva app disponible, salud falsa o rutas de pago activas | 5xx inesperado, error de integridad, endpoint que acepta pago | Parar liberación del tráfico; mantener PREFREEZE; diagnosticar con evidencia redaccionada, usar solo release segura compatible previamente probada | Restaurar una imagen antigua que reactive PayPal |
| Servicio sano, regresión funcional | Fallo en FIFO, autenticación o gestión interna S01 | Mantener congelada puesta en marcha, plan de recuperación y restauración probado con preservación de toda solicitud | Revertir BD a una copia antigua perdiendo solicitudes |
| Ambigüedad de transacción | Referencia de proveedor o pago incierto | Impedir nuevos intentos, preservar pedido/consentimiento/evidencia; conciliación humana delimitada | Reintentar cobro, reenviar presupuesto o borrar orden |

## Regresión añadida: arranque real del candidato + PostgreSQL 18

`fiscal_app_export/tests/qa_s01_recovery_gate_pg18.py` se permite solo en GitHub Actions y utiliza PostgreSQL 18 local, sin URL de Railway. Sus comprobaciones:
1. Una BD vacía no puede arrancar la aplicación nueva ni sufre cambios implícitos.
2. Tras ejecutar `bootstrap_db.py` **únicamente en CI**, `startup_schema_gate.py` confirma head S01.
3. Se crean seis expedientes **enteramente sintéticos**; uno `quote_sent` con token ficticio caducado.
4. Un cliente de prueba real Flask contra la base migrada confirma salud HTTP, **7 rutas financieras rechazadas**, página de pago informativa y antigua confirmación neutralizada. Bloquea llamadas de red/email y escrituras financieras; compara huella de todos los expedientes antes y después.
5. Si Alembic se vuelve deliberadamente antiguo **solo en DB temporal CI**, el arranque falla cerrado sin alterar expedientes; al restaurar head exacto, vuelve a pasar. Con CHECK retirado temporalmente, vuelve a fallar sin autoreparación.

**Prueba de límites:** esta integración CI no ensaya otro artefacto deployable, no activa tráfico TCP real de staging y no garantiza disponibilidad de rollback; prueba solo propiedades en procesos sintéticos sobre PG18. La anterior PR #59 conserva test real DDL `v5→z9` con 6 expedientes ficticios.

## Condiciones para solicitar autorización separada de staging

**Preflight sin cambios de infraestructura:** confirmar de forma verificable mecanismo de control de autodespliegue y source triggers; validar aislamiento real de las variables `DATABASE_URL` **por alias/destino no secreto, nunca credenciales**; revisar dos alertas vigentes de PostgreSQL prod sin volcar datos personales; comprobar que staging dispone de base y volumen independientes, restauración no productiva y networking sin acceso a proveedores.

**Operación futura bajo autorización separada:** staging con release exacta S01, base aislada nueva/sintética que pueda migrarse, proveedor email y cobros efectivamente deshabilitados, smoke test login/FIFO/admin/C1 y endpoints 503, posibilidad real de recuperar app/BD sin cambiar la base productiva. No desplegar antes de aceptar procedimiento de aislamiento, verificar SHA, bootstrap de esquema y desactivar desencadenantes no deseados.

## Gates obligatorios pendientes antes de producción

- Artifact/image de contingencia fail-closed **distinto del `main` antiguo**, compatible con `z9...`, desplegable y probado en staging.
- Rollback de servicio sin `alembic downgrade`, `stamp`, borrado de expedientes o apertura de PayPal.
- Ensayo con respaldo fresco privado restaurado y cotejo de TODAS las filas, no solo conteos; verificación schema metadata y constraints.
- Staging validada, control de despliegue automático y alcance OAuth/config de correo/Stripe/PayPal.
- Autorización explícita separada para staging, PR merge, backup y migración en producción, publicación.
