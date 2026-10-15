# C2 — Revisión independiente de C1 y dependencias S01
**Fecha:** 13 de octubre de 2026  
**Dictamen:** **NO-GO para merge, despliegue y activación financiera.**  
**Tipo:** auditoría estática de GitHub y evidencia CI; ninguna modificación de código o de servicio.

## 1. Baseline inmutable y alcance

- Repositorio: `MarianoSevilla/fiscal-cripto-`.
- Producción / `main`, según SHA de GitHub: `56882073295faae3bd1bc3632288a970acb330da`. Este chequeo **no verifica por sí solo Railway actual**.
- PR C1 **#56**, `draft`, **sin merge**, base rama de PR **#53**, SHA exacto `598bb0912ad0dc4521aaba881512b13aa268b4eb`.
- Comparación #56 vs #53: **3 commits y 7 archivos**; no se modifican migraciones, `Procfile`, secretos, proveedor ni endpoint Stripe.
- Comparación árbol #56 vs `main`: **74 commits, 69 archivos cambiados**. La cadena acumulada incluye contratos S01, PREFREEZE, PayPal inerte, migraciones, G04, G07 y G06. No es válido fusionar selectivamente #56 sin las dependencias ni saltarse el orden.
- PR PayPal U04 **#29** conserva evidencia histórica, pero su head Alembic paralelo NO debe incorporarse. PR Connect 50/50 **#54** queda fuera del árbol #56 y no es el contrato aprobado (comisiones de procesamiento 30 % Mariano / 70 % Rafa).
- El alcance C1 autorizado: recibir y gestionar solicitudes internamente; **no enviar presupuestos, no aceptarlos para cobrar, no generar enlaces, no efectuar cobros**. PayPal retirado como método futuro S01, historial intacto.

## 2. Evidencia positiva, sin inferir condiciones Live

La **CI #85**, https://github.com/MarianoSevilla/fiscal-cripto-/actions/runs/38402826335, terminó `SUCCESS` sobre **exactamente** `598bb0912ad0dc4521aaba881512b13aa268b4eb`:
- Backend: **1.541 passed, 63 skipped**, sin errores; lock 20 dependencias directas / 57 pins runtime.
- PostgreSQL 18, Alembic lineal, gate G04 y pruebas históricas de PayPal: SUCCESS.
- Browser navigation: SUCCESS.
- Las nuevas rutas `/gestion/nota` y `/gestion/estado` conservan control de rol asesor/admin, token CSRF en sesión, cabecera obligatoria, rechazo de Origin distinto cuando se declara, limitador y validación de estado. Se observan APIs financieras antiguas con PREFREEZE sin cambios y stubs de PayPal inertes.
- El formulario `/api/asesoramiento/solicitar` queda activo. La nueva nota interna no envía email ni crea cobros; la transición de estado C1 no envía email.
- El panel elimina opciones de enviar presupuesto, reenviar enlace o mensaje externo. Se inhiben borrado y marcas de prueba en la UI; las APIs heredadas permanecen bloqueadas por PREFREEZE.
- La UI escapa nombres, mensajes y notas insertados en HTML; no hay indicio de que estas rutas C1 creen sesiones Stripe ni órdenes PayPal.

**Límite de evidencia:** el navegador genérico y el job PG18 de CI **no prueban de extremo a extremo** el nuevo flujo C1 ni una carrera entre sus rutas de estado y escrituras relacionadas; los tests C1 añadidos usan SQLite y mocks.

## 3. Hallazgos pendientes

### C2-01 — ALTA · Endurecer detector de evidencia financiera histórica
- `fiscal_app_export/app.py`, `_c1_safe_to_change_state` (aprox. 4991–5007).
- Actualmente comprueba importes, fechas principales, IDs proveedor, token, aceptación y filas `S01StripeCheckoutAttempt`. **No comprueba** campos de evidencia como `commission_rate_bps`, `quoted_by_user_id`, `quote_message`, `quote_expires_at`, `quote_acceptance_ip`, `quote_acceptance_user_agent`; tampoco contrasta historial de estados/AuditLog.
- **Riesgo condicionado:** si un registro legado o parcialmente reconciliado tiene `status=submitted`, campos principales nulos pero evidencia secundaria conservada, C1 podría clasificarlo como editable y cambiarle el estado administrativo. No se ha demostrado que exista tal registro real ni se afirma que pueda cobrar.
- **Cierre exigido:** política explícita y fail-closed para cualquier evidencia económica histórica; añadir fixtures de registros legados parciales y pruebas de no mutación/auditoría, sin limpiar campos históricos ni normalizarlos retroactivamente.

### C2-02 — ALTA · Demostrar bloqueo real PostgreSQL 18 para las rutas C1
- `fiscal_app_export/tests/test_s01_c1_management.py` (169 líneas) usa SQLite; en SQLite `with_for_update()` no equivale a los bloqueos de filas de PostgreSQL.
- Las pruebas PG18 de CI validan el bloqueo histórico y otras carreras S01, **no** la nueva ruta `/gestion/estado` bajo dos conexiones/procesos, ni su interacción con evidencia de intento/aceptación.
- **Cierre exigido:** test aislado PG18 con múltiples conexiones y barreras, bloqueo de fila concurrente, preservación de snapshots, intento insertado/precedente, rollback/crash y comparación de antes/después. No proveedor ni DB real.

### C2-03 — MEDIA · Panel habilita cambio de estado aunque el servidor deniegue
- `static/admin-asesoramiento.html` aprox. línea 567: `c1Editable` depende exclusivamente de `status`.
- `app.py` nueva ruta de estado también requiere ausencia de evidencia financiera. En un expediente `submitted` con `paypal_order_id` histórico, el panel muestra «Guardar» y la API responde 409. La prueba `test_c1_existing_financial_evidence_blocks_status_but_keeps_notes` demuestra esta situación en datos sintéticos.
- **Cierre:** API de solo lectura/indicador `state_editable` derivado del mismo criterio backend (o UI conservadora) y mensajes consistentes; nunca confiar en el cliente como control de seguridad.

### C2-04 — MEDIA · Comunicación pública de tarifas heredadas durante suspensión
- `app.py` `/api/asesoramiento/precios` (aprox. 4728–4734) sigue publicando precios base fijos heredados, y `static/asesoramiento-fiscal.html` (aprox. 454–469) los representa como importes en servicios. La suspensión sí aparece en el hero.
- Riesgo de confundir tarifas de referencia con oferta presupuestada o contratación futura cuando el precio S01 está sujeto al presupuesto de Rafa + 30 % y ninguna cotización debe enviarse en C1.
- **Cierre:** retirar importes públicos de S01 durante C1 o identificarlos inequívocamente como información histórica no contractual; prueba de contenido desktop/móvil y de comunicación/SEO.

### C2-05 — MEDIA · Estados «esperando información» sin canal de respuesta
- La ruta de mensaje externo `/mensaje` permanece correctamente bloqueada, pero C1 permite pasar a `pendiente_info`/`waiting_user_info` sin enviar petición al cliente. El panel dice «Esperar respuesta del cliente» aunque puede no existir mensaje alguno.
- **Cierre:** separar estados exclusivamente internos de estados que presuponen notificación, o definir una vía segura de comunicación sin presupuestos sujeta a revisión/autorización específica. C1 no autoriza reactivar mensajes comerciales.

### C2-06 — SEGUIMIENTO · Evidencia de información/consentimiento de solicitud
- `static/pedir-asesoramiento.html` exige checkbox legal en cliente, pero el JSON enviado (aprox. 222–233) no incluye prueba/versionado de esa confirmación; `app.py` `advisory_solicitar` (aprox. 4740–4825) tampoco lo exige ni almacena.
- Es comportamiento heredado; **no se afirma que el tratamiento carezca de base jurídica**. Aun así, no es una prueba verificable de lo que el usuario vio o aceptó. En transición y futuro G06 deben definirse información y evidencia adecuadas con revisión legal, minimización de datos y alcance separado del consentimiento para cobros.
- **Cierre:** inventariar base jurídica/información exigible; control server-side y registro mínimo, versionado, sin capturar más PII por defecto.

## 4. Bloqueadores de integración ya conocidos en la cadena

1. **G04 arranque fail-closed:** el `Procfile` usa `startup_schema_gate.py` en READ ONLY y requiere Alembic head y constraints exactos. Un despliegue antes de la migración administrada aprobada puede dejar la web sin iniciar. Una CI verde no salva este bloqueo.
2. **G05 histórico:** conciliar PayPal con evidencia actual y sin asumir cero cobros; no descartar órdenes inciertas ni borrar historial.
3. Revisar de forma independiente el conjunto apilado hasta #56 (y migraciones), evitar fusionar PR PayPal U04 #29, PR Connect #54 50/50 o ramas de auditoría laterales como si fueran motores productivos.
4. **Stripe Connect no activo**: G06/G07/G08 y pruebas externas requerirán autorización diferente; no usar configuración MERU/Stripe actual como prueba de viabilidad de la cuenta de Rafa.
5. **Staging actualmente aislado**: no considerar tests unitarios ni backend sintético equivalente a ensayos de staging/rollback.
6. Preparar backup restaurable, verificación esquema real con mínimos agregados y runbook, sin acceder a PII ni modificar Railway hasta su autorización por separado.

## 5. Dictamen C2 y secuencia recomendada

**C2 es una revisión estática finalizada con hallazgos. PR #56: CAMBIOS SOLICITADOS / NO-GO para integración.**
El hallazgo no prueba explotación, cobro o fallo productivo; distingue claramente fallos reproducidos, garantías parciales y escenarios condicionales.

Antes de autorizar una integración:
1. Preparar una **PR de remediación C2-R01**, independiente y apilada sobre el SHA exacto #56, que corrija C2-01 a C2-05 con pruebas; C2-06 puede cerrarse en una revisión de privacidad específica pero no ignorarse.
2. Correr CI completa + PG18 nueva + pruebas del frontend C1 y revisar diff contra el commit base sin mezclar código Connect de #54.
3. Ejecutar revisión independiente del código corregido y de los gates acumulados.
4. Preparar plan de merge seguro, migraciones y despliegue solo bajo una **autorización expresa posterior**.

**Acciones realizadas en C2:** lecturas GitHub y CI; actualización documental de auditoría y comentario de revisión en PR #56. **No** merge, deploy, cambios de código funcional, DB, Railway, Stripe, PayPal, MERU, cobros, devoluciones ni datos personales.