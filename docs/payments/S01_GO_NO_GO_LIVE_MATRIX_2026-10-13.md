# S01 — Matriz de autorización financiera: GO / NO-GO (13/10/2026)

**DICTAMEN ACTUAL: NO-GO PARA COBROS REALES, MERGE Y DESPLIEGUE.**

Documento de auditoría y planificación **únicamente**: no introduce código, variables, migraciones ni instrucciones de ejecución contra producción. El informe se basa en lectura de GitHub y en la evidencia *declarada por el propietario* del ensayo de restauración en el Mac mini. No se han consultado directamente servicios de producción, Stripe, PayPal, MERU ni datos personales.

## 1. Contexto y alcance exactos

- Repositorio: MarianoSevilla/fiscal-cripto-; **main** comprobado en SHA `56882073295faae3bd1bc3632288a970acb330da`.
- Cobro S01: **únicamente** presupuestos personalizados de asesoramiento fiscal, valorados por Rafa. Precio comercial previsto: honorarios de Rafa + 30 % del importe de honorarios, redondeo a céntimos HALF_UP; el total pagado por el cliente y tratamiento tributario final requieren conformidad contractual y fiscal. No confundir comisión del 30 % con una decisión sobre IVA.
- Stripe Checkout alojado por Stripe, una sola operación por presupuesto, tarjeta y wallets según disponibilidad. Suscripciones **S02** fuera de este alcance.
- La aplicación **no hace facturas**: Rafa las prepara/entrega externamente. Esa exclusión funcional **no sustituye** la necesidad de definir la identidad del prestador, quién figura como comerciante en Stripe y responsabilidades fiscales/contractuales y de reembolso.
- Destino bancario previsto: IBAN virtual EUR de MERU/Banking Circle registrado en Stripe según información del propietario; **no hay evidencia independiente** de que se admitan y liquiden payouts y de su tratamiento bancario.

### Estado de ramas — lectura verificada a 13/10/2026

| PR | Función | Estado en GitHub |
| --- | --- | --- |
| [#29](https://github.com/MarianoSevilla/fiscal-cripto-/pull/29) | U04 conciliación PayPal y migración divergente | Abierta, borrador, NO integrada |
| [#30](https://github.com/MarianoSevilla/fiscal-cripto-/pull/30) | PREFREEZE, suspensión de escrituras | Abierta, borrador, NO integrada aisladamente |
| [#32](https://github.com/MarianoSevilla/fiscal-cripto-/pull/32) | Firma webhook Stripe | Abierta, borrador, NO integrada aisladamente |
| [#33–#40](https://github.com/MarianoSevilla/fiscal-cripto-/pulls) | Cálculo, reservas, concurrencia, webhooks y outbox sintéticos | Abiertas, borrador, NO integradas |
| [#41](https://github.com/MarianoSevilla/fiscal-cripto-/pull/41) | Retirada ejecutable PayPal, historia Alembic S01 lineal | Abierta, borrador, base main |
| [#42](https://github.com/MarianoSevilla/fiscal-cripto-/pull/42) | Auditoría independiente inicial | Abierta, borrador, base #41 |
| [#43](https://github.com/MarianoSevilla/fiscal-cripto-/pull/43) | Corrección de referencias históricas y StripeObject v16 | Abierta, borrador, base #41 |
| [#44](https://github.com/MarianoSevilla/fiscal-cripto-/pull/44) | Carrera real PG18 reemisión/reserva | Abierta, borrador, base #43 |
| [#45](https://github.com/MarianoSevilla/fiscal-cripto-/pull/45) | Ensayo local de copia restaurada | Abierta, borrador, base #44 |

**Advertencia de integración:** el árbol validado de #45 **no está en main ni se ha desplegado**. Los controles PASS no implican que producción ejecute ese código. No combinar automáticamente #29 con #41: U04 propone `w6x7y8z9a0b1`, un head divergente respecto de la línea S01 `v5w6x7y8z9a0 → x7y8z9a0b1c2 → y8z9a0b1c2d3 → z9a0b1c2d3e4`.

## 2. Regla formal de autorización

Estados: **PASS aislado** = superado en rama/test/copia restaurada con el alcance indicado, **PARCIAL** = existen garantías útiles pero no el flujo operativo entero, **ABIERTO** = falta implementación o evidencia, **BLOQUEADO** = requiere una decisión o dependencia previa.

Solo podrá recomendarse **GO de activación de cobros reales** cuando todos los gates G00–G16 estén cerrados con evidencia verificable sobre **un mismo SHA de entrega**, tras revisión independiente y autorización **explícita y separada** del propietario para cada clase de acción: merge, migración/operaciones Railway, configuración Stripe/PayPal/MERU y transacciones financieras. Ni una CI verde ni esta matriz sustituyen esas autorizaciones.

| Gate | Control exigido | Estado hoy | Evidencia existente / criterio objetivo para cerrar | Responsable propuesto |
| --- | --- | --- | --- | --- |
| **G00** | Congelación y ausencia de procesos antiguos capaces de cobrar | **ABIERTO** | #30 prueba PREFREEZE en CI, pero no hay prueba operativa de que todos los procesos U03, peticiones ya iniciadas y eventuales workers hayan cesado. Certificar inventario de versiones/instancias, drenaje y punto UTC de corte antes de migrar. | Propietario + ingeniería |
| **G01** | Presupuestos conservan evidencia financiera | **PASS aislado** | #43: bloqueo 409 y conservación de referencias PayPal/Stripe cuando hubo actividad; #44: carrera real PG18 con dos procesos y orden de locks; [CI #56](https://github.com/MarianoSevilla/fiscal-cripto-/actions/runs/38320523414) y [#57](https://github.com/MarianoSevilla/fiscal-cripto-/actions/runs/38321351739). Revalidar en composición HTTP final. | Ingeniería |
| **G02** | Contrato StripeObject SDK 16 e idempotencia de reserva | **PARCIAL** | #43 valida objeto SDK tipado sintético, #44 reserva/reescritura; no hay deserialización HTTP de proveedor ni adaptador real, ni recuperación autorizada de `creating/uncertain`. Requerir tests de respuesta HTTP simulada fiel y de errores de red/ACK/24h sin repetir intentos. | Ingeniería |
| **G03** | Migración desde copia íntegra de producción | **PASS local reportado** | #45 sobre SHA `9086bee60b52d0cde269ad06bb8388b60125873c`: preflight PGDMP/SHA-256, restore PG18, revisión inicial `v5w6x7y8z9a0`, dos pasadas bootstrap, preservación de recuentos/huellas de columnas históricas, tres tablas S01 vacías, comisiones legacy NULL, índices y constraints; `S01 REHEARSAL: PASS` aportado por el propietario el 13/10/2026. [CI #62](https://github.com/MarianoSevilla/fiscal-cripto-/actions/runs/38324451927) 1.450 passed, 63 skipped, PG18 y navegador SUCCESS. Sin exponer backup. **No certifica actualidad del estado financiero de PayPal.** | Propietario + ingeniería |
| **G04** | Ningún DDL sorpresa al importar/arrancar app en Live | **ABIERTO** | El Procfile inicia `bootstrap_db.py` antes de Gunicorn; `bootstrap_db.py` importa `app.py`, que llama `db.create_all()` antes de verificar el estado de Alembic. El éxito G03 no elimina este riesgo. Separar el gate de migración del arranque, probar ausencia de DDL de importación y desplegar solo tras protocolo de esquema autorizado. | Ingeniería + revisor |
| **G05** | Cierre financiero y retirada PayPal | **ABIERTO** | #41 elimina ejecuciones nuevas de PayPal y mantiene IDs históricos; **no** acredita ausencia de órdenes, capturas, reembolsos, ACK perdidos ni eventos fallidos. Inventario de metadatos de DB y contraste **autorizado en modo lectura** con proveedor, periodo y saldos, acta de discrepancias y bloqueo de expedientes inciertos. #29 se conserva, sin integrarla automáticamente. | Propietario + responsable financiero |
| **G06** | Titularidad del cobro, precio final e impuestos | **ABIERTO** | Confirmación escrita de Rafa y titular Stripe: quién presta servicio, quién aparece como vendedor/prestador, quién recibe los fondos, cómo se documentan honorarios, 30 %, IVA/impuestos, cancelaciones y devoluciones. **No introducir facturas en la app.** No afirmar que el 30 % ya es el importe fiscal final. | Propietario + Rafa/asesor |
| **G07** | Endpoint nuevo de presupuesto y aceptación | **ABIERTO** | Ruta S01 separada, permisos y token opaco, vencimiento, límite de solicitudes, aceptación expresa del importe final, snapshot auditable, CSRF cuando corresponda, protección frente a reemisión y simultaneidad. Nunca marcar pagado por visitar success_url. Actualmente página /pagar mantiene aviso de suspensión. | Ingeniería |
| **G08** | Checkout alojado e integración con proveedor en modo de prueba | **ABIERTO** | El orquestador existente es TEST sintético con proveedor inyectado, `FLASK_ENV=testing` y `is_test=True`; no conecta Stripe. Adaptador separado y revisado, pruebas de entorno Stripe Test **solo con autorización** para tocar el servicio, correlación final de amount/currency/IDs, sin reutilizar credenciales Live. | Ingeniería + propietario |
| **G09** | Webhook HTTP S01 firmado, transaccional y aislado | **ABIERTO** | #32 verifica firma en código bajo PREFREEZE; #37–#40 prueban evento firmado y outbox sintéticos, pero la ruta pública antigua /api/webhooks/stripe sigue respondiendo 503. Nueva ruta revisada con bytes originales, firma actual, limites, deduplicación, correlación exacta y commit atómico; 2xx **solo** tras persistencia. No rehabilitar finalizador legacy. | Ingeniería + revisor de seguridad |
| **G10** | Conciliación Stripe incierto/caídas | **ABIERTO** | Procedimiento para `creating`, `uncertain`, `ready` y faltas de ACK/red/SIGKILL; consulta autorizada del **mismo** objeto, nunca crear otra sesión por deducción ni reintentar ciegamente fuera de la ventana de idempotencia; reconciliación de webhooks tardíos, fuera de orden y no entregados, evidencias y acción manual. | Ingeniería + operaciones |
| **G11** | Reembolsos, contracargos, pagos asíncronos y reversos | **ABIERTO** | Definir estados, eventos, resolución, compensación y prohibición de doble cierre. Tests de refund/dispute, duplicados, disputa tras paid y recuperación; tratamiento de pagos no instantáneos si la cuenta los expone. | Ingeniería + propietario |
| **G12** | Avisos de pago y recuperación outbox | **PARCIAL** | #40 crea dos filas pendientes por cobro en una transacción, no entrega correos. Falta dispatcher con leases/idempotencia del proveedor si disponible, estados y reintentos seguros, recuperación de caída tras envío y antes del ACK, redacción no sensible y operativa manual. Exactamente una fila de outbox **no garantiza** un solo email. | Ingeniería |
| **G13** | Payout y recepción efectiva MERU/Banking Circle | **ABIERTO** | IBAN incorporado a Stripe según propietario, **sin prueba de payout permitido ni recibido**. Obtener confirmación documental del titular/reglas de origen y terceros, divisa, límites, rechazo/devolución, saldo y conciliación. Ensayos de transferencia **solo con permiso separado** y cumpliendo normativa y condiciones del proveedor. | Propietario + MERU/Stripe |
| **G14** | Pruebas de integración y abuso de S01 | **ABIERTO** | CI sobre árbol final: pruebas PostgreSQL 18 de races/rollbacks, autenticación y permisos, test de firma, replay, importe alterado, páginas móvil/escritorio, incompatibilidades SDK, secretos ausentes; E2E de Stripe Test externo en staging aislado **solo tras permiso**. No asumir que #62 cubre código futuro. | Ingeniería + QA |
| **G15** | Revisión independiente y release seguro | **ABIERTO** | Revisar diff acumulado de PR #33–#45, colisiones entre #30/#32/#41 y #29, sha main actual, cierre de findings y CI sobre SHA final. Plan de reversión **sin bajar tablas ni perder historiales financieros**; procedimiento de corte, despliegue y autorización escalonada. | Revisor independiente + propietario |
| **G16** | Monitorización y respuesta a incidentes | **ABIERTO** | Alertas 5xx, webhook 503/fallos, intentos inciertos, cobros confirmados no conciliados, salidas bancarias, outbox retenido; responsables, runbook, ventanas y pausa inmediata del cobro con consultas permitidas. No reactivar PayPal/U03 como rollback. | Operaciones + propietario |

**No son 17 errores confirmados en producción**: la mayoría son controles de seguridad y operación **pendientes de construir, demostrar o autorizar** antes del despliegue. No se ha observado un incidente financiero real en esta auditoría.

## 3. Camino crítico y entregas separadas

| Orden | Entrega recomendada | Dependencias / definición de terminado |
| --- | --- | --- |
| **E1** | **S01-R01: conciliación PayPal read-only, sin afectar runtime** | Preparar plantilla de inventario (conteos de órdenes/capturas, intentos inciertos y estados por corte UTC), datos estrictamente anonimizados, validación del proveedor por propietario autorizado y política para discrepancias. G05; sin acceso ni modificación de cuentas en esta fase. |
| **E2** | **S01-R02: contención de DDL en arranque** | Proponer diseño fail-closed para app import y bootstrap de DB. Tests de arranque sobre restauración aislada, revisión del grafo Alembic y rollback compatible; G04. No migrar producción. |
| **E3** | **S01-R03: contrato comercial y liquidación** | Recoger criterios del propietario/Rafa y confirmación de MERU/Stripe: prestación, cobro total, 30 %, IVA y payout. Gates G06 y G13; no añadir facturación a la app. |
| **E4** | **S01-R04: flujo HTTP de aceptación y Checkout TEST** | Diseño y código en rama separada, persistencia y lock ordering auditados, endpoint nuevo, protección antifraude, retorno sin confirmación de pago. Gates G02/G07/G08. Ninguna llamada al proveedor sin autorización. |
| **E5** | **S01-R05: receptor firmado, reconciliación y reembolsos** | Nuevo consumidor live-capable **separado de legacy**, tests E2E sintéticos/PG18; incidentes, replay, refunds/disputes. Gates G09/G10/G11. |
| **E6** | **S01-R06: outbox y observabilidad** | Worker dedicado, garantías de entrega, alertas, runbook y semántica de reintento; G12/G16. |
| **E7** | **S01-R07: revisión final y plan de rollout** | Resolver cadena de PR, congelar todos los procesos antiguos, ensayo de migration sobre backup representativo, CI/review del mismo SHA, autorizaciones separadas y reversible cutover; G00/G03/G14/G15. |

No iniciar E4–E7 únicamente por disponer de E1/E2: respetar el resto de dependencias del gate.

### Decisión de arquitectura PayPal

La línea S01 #41 **retira PayPal ejecutable** y preserva referencias históricas. La PR #29 desarrolla una vía alternativa de conciliación PayPal con esquema divergente, **no integrable automáticamente**. Propuesta sujeta a decisión del propietario: mantener PayPal desactivado para nuevas operaciones y construir **solo el mecanismo histórico read-only de conciliación** que resulte necesario; no reabrir órdenes, capturas o la migración #29 por defecto. Hasta cerrar G05, todo expediente con resultado financiero incierto permanece bloqueado.

### Semántica de un futuro GO

No existe un solo botón de GO. Preparar actas separadas: (i) autorización de merge del código revisado; (ii) migración/deploy a entorno staging bajo condiciones verificadas; (iii) ensayos Stripe Test y aceptación bancaria **sin fondos reales**; (iv) despliegue productivo congelado, con verificación de SHA y ausencia de U03; (v) activación financiera Live bajo supervisión y protocolo de reversión. Toda etapa requiere prueba de cumplimiento y consentimiento específico, no derivado de esta matriz.

## 4. Fuentes de evidencia y límites

- [Auditoría independiente #42](https://github.com/MarianoSevilla/fiscal-cripto-/pull/42) y su fichero `docs/payments/S01_PREINTEGRATION_AUDIT_2026-10-13.md` (observaciones iniciales, anteriores a las correcciones #43–#45).
- [#43](https://github.com/MarianoSevilla/fiscal-cripto-/pull/43): AUD-001 y AUD-003 corregidos para TEST; [CI #56](https://github.com/MarianoSevilla/fiscal-cripto-/actions/runs/38320523414) SUCCESS.
- [#44](https://github.com/MarianoSevilla/fiscal-cripto-/pull/44): carrera PG18 y verificación bloqueo 409; [CI #57](https://github.com/MarianoSevilla/fiscal-cripto-/actions/runs/38321351739) SUCCESS.
- [#45](https://github.com/MarianoSevilla/fiscal-cripto-/pull/45): pruebas de integridad de backup y restauración en Mac mini sobre commit final `9086bee60b52d0cde269ad06bb8388b60125873c`; [CI #62](https://github.com/MarianoSevilla/fiscal-cripto-/actions/runs/38324451927) SUCCESS. El propietario informó: `S01 PRECHECK ... OK`, `S01 RESTORE ... OK`, dos `S01 UPGRADE ... OK` y `S01 REHEARSAL: PASS`.
- [PR #29](https://github.com/MarianoSevilla/fiscal-cripto-/pull/29): U04 PayPal pendiente e independiente; [#30](https://github.com/MarianoSevilla/fiscal-cripto-/pull/30): PREFREEZE y procedimiento de retirada completa de procesos U03; [#32](https://github.com/MarianoSevilla/fiscal-cripto-/pull/32): firma Stripe.
- Árbol S01 revisado está en #45, no en `main`. No se ha verificado la versión concreta de ejecución de Railway ni el inventario en producción. No existe evidencia recibida de movimientos PayPal o payout Stripe/MERU.

**NO-GO GLOBAL VIGENTE.** Este documento **no concede permiso** para consultas productivas, acceso a información identificativa, cambios de configuración, integración de PR, despliegue, migraciones en producción, pagos de prueba con proveedor externo, pagos Live, refunds o transferencias. Cualquier excepción requiere encargo y autorización nuevos con alcance explícito.
