# S01 — Auditoría independiente G07/G08: aceptación de presupuesto y Checkout sintético

**Fecha:** 13/10/2026  
**Código revisado:** [PR #50](https://github.com/MarianoSevilla/fiscal-cripto-/pull/50), SHA **`7fb321d893a2fc2f9e583110dc60be5a4f8b7b72`**, base PR #49 `b19cb1030e2ff5c5f9e297311af6661e34075e62`.  
**Dictamen:** **NO-GO para integrar la aceptación como vía real de pago**. La rama sigue siendo únicamente un **harness sintético desconectado**; no existe incidente observado, cobro o explotación en producción.

Este es un informe de revisión **separado de la implementación #50**: ninguna modificación del código de pagos de la PR auditada, de `app.py`, migraciones, claves, webhooks, Stripe o Railway. El código de pruebas de esta auditoría utiliza SQLite efímera y un proveedor en memoria; no accede a clientes, backup, servicios o pagos reales.

## 1. Evidencia auditada

| Documento/código | Observación |
| --- | --- |
| `advisory_s01_synthetic_acceptance_http.py` | GET minimiza PII y genera CSRF; POST valida importe exacto, token, origen y flag sintético; **hace COMMIT de `quote_accepted_at` antes de llamar al orquestador** |
| `advisory_s01_test_orchestrator.py` | `_reserve` exige `quote_sent`, `is_test`, ausencia de referencias e intento único, pero **no comprueba `quote_accepted_at`** |
| `advisory_s01_checkout.py` | Verifica total, fingerprint, expiración y sesión `cs_test_`, sin IO |
| `models.py` | `quote_accepted_at`, `quote_acceptance_ip`, `quote_acceptance_user_agent` existen, pero no contienen snapshot inmutable de la oferta, versión de términos ni prueba de aceptación por sujeto autenticado |
| `app.py` | No importa/registra el nuevo blueprint; se conserva PREFREEZE de las rutas de cobro existentes |
| `tests/test_s01_synthetic_acceptance_http.py` | Pruebas positivas/negativas HTTP ficticias de CSRF, reenvío, importe y flag, pero no exigen invariante de aceptación en el orquestador ni recuperación atómica de un fallo previo a reserva |
| [CI #72](https://github.com/MarianoSevilla/fiscal-cripto-/actions/runs/38378239454) | **SUCCESS**, 1.475 passed / 63 skipped, PG18 y navegación SUCCESS; CI verde de la implementación no acredita que se hayan cubierto los casos faltantes |

## 2. Hallazgos priorizados

### G07-AUD-001 — ALTO: aceptación no obligatoria en el límite de negocio

**Localización:** `advisory_s01_test_orchestrator.py::_reserve()` y `advisory_s01_synthetic_acceptance_http.py::accept_quote()`.

**Hecho comprobable en código:** `_reserve()` puede construir `S01Reservation`, persistir un intento `creating`, contactar al proveedor inyectado y registrar `ready` **sin condición previa sobre `quote_accepted_at`**. El nuevo endpoint sí registra aceptación, pero un llamador directo al orquestador (incluida una futura ruta o tarea interna) elude ese orden lógico. Las pruebas originales `test_committed_reservation_before_provider_and_exact_link` también construyen una sesión sin `quote_accepted_at` en la fixture.

**Impacto futuro:** riesgo de crear un Checkout (y, posteriormente, cobrar) sin prueba de que el cliente haya aceptado el presupuesto. **No existe ruta Live conectada actualmente**, de modo que no se ha observado ese efecto financiero real.

**Reproducción sintética de auditoría:** `test_aud001_checkout_requires_persisted_quote_acceptance`, marcada `xfail(strict=True)`. Expresa el comportamiento seguro esperado, hoy incumplido. Sin llamadas a Stripe.

**Remediación exigida:** el servicio que inicia Checkout debe verificar aceptación duradera **en la misma transacción/bloqueo SQL de la reserva**, ligándola al snapshot inmutable del importe, divisa, expiración y términos. La UI/HTTP no debe ser la única barrera. Incluir pruebas negativas de invocación directa sin aceptación y reservas con aceptación revocada o snapshot alterado.

### G07-AUD-002 — ALTO: aceptación huérfana entre dos COMMIT

**Localización:** `accept_quote()` realiza `db.session.commit()` de `quote_accepted_at` y, **después**, `create_synthetic_checkout()` intenta reservar en una transacción nueva. `_eligible()` excluye cualquier `quote_accepted_at` existente; además, la reemisión de presupuesto bloquea documentos aceptados.

**Escenario:** caída del proceso, validación fallida o error de BD *entre ambos commits*, antes de que exista `S01StripeCheckoutAttempt`. Queda una aceptación persistida, **cero intentos** y un presupuesto que GET ya no permite aceptar de nuevo. La simulación de fallo previo a reserva muestra el contrato faltante. Este resultado **no es doble cobro**, pero sí bloqueo sin ruta de recuperación especificada. Los errores **después** de una reserva confirmada son distintos: deben permanecer `creating`/`uncertain` y nunca dar lugar a un segundo intento ciego.

**Reproducción sintética:** `test_aud002_no_orphan_accepted_quote_after_pre_reservation_failure`, `xfail(strict=True)`, inyecta una excepción controlada antes de reservar y exige que no quede la aceptación huérfana.

**Remediación exigida:** **una única transacción** debe validar aceptación, fijar el snapshot y crear la reserva `creating`, con COMMIT **antes** de cualquier llamada a proveedor. Si falla **antes de ese COMMIT**, rollback de ambos. Si falla **después**, conservar un único intento incierto y procedimiento de conciliación de ese mismo objeto. Probar SIGKILL/timeout/errores antes y después del COMMIT y rechazo de reintentos concurrentes.

### G07-AUD-003 — MEDIO: evidencia de consentimiento insuficiente para Live

**Localización:** `quote_accepted_at` y `quote_acceptance_user_agent` genérico. No hay snapshot inmutable de precio y versión de términos aceptados, evento de auditoría con actor/verificación de identidad o aceptación contractual validada por Rafa/propietario.

**Impacto:** ante disputa, difícil demostrar qué condiciones e importe exacto se aceptaron y por quién. El CSRF prueba continuidad de una sesión **de prueba**; **no es identidad del cliente**. Una URL/token bearer debe tratarse como secreto, pero no demuestra por sí solo identificación o validez jurídica del consentimiento.

**Remediación:** definir con G06 el texto legal/importe final/impuestos y merchant-of-record; snapshot de oferta, hash/version de términos, instante UTC, mecanismo de autenticación apropiado y auditoría resistente a sobreescritura. **No se propone crear facturas en la app**: las emite Rafa externamente.

### G07-AUD-004 — MEDIO: concurrencia HTTP de aceptación no acreditada en PostgreSQL 18

El nuevo `accept_quote()` tiene `with_for_update()` y el intento posee constraint `UNIQUE(advisory_id)`, pero las pruebas nuevas HTTP son secuenciales y SQLite. La CI PG18 existente valida carreras de **reemisión vs reserva**, no dos aceptaciones HTTP reales que compiten por el mismo CSRF/token ni el fallo inyectado entre consentimiento y reserva.

**Remediación:** ensayo PG18 **con dos sesiones/procesos**, barreras de sincronización antes/después del COMMIT y pruebas de obtención de locks, errores SQL y atomicidad de consentimiento/reserva. Exigir exactamente un `attempt` y cero cobros; el perdedor retorna 409 sin inventar nuevo `idempotency_key`.

### G07-AUD-005 — MEDIO/PRODUCTO: comportamiento multiventana y recuperación tras error

Cada GET reemplaza un único nonce CSRF por sesión, por lo que abrir una segunda pestaña invalida el formulario de la primera. Junto al estado `accepted` huérfano, no existe una vía de recuperación sin una intervención administrativa segura. No se considera una vulnerabilidad de acceso en el harness; sí una limitación UX con impacto real si se reutiliza.

**Remediación:** diseñar la caducidad y administración de nonces (sesión individual por quote o conjunto acotado) y una página de estado sin repetir Checkout: `quote_ready`, `checkout_creating/uncertain`, `ready`, `paid` o atención requerida. Nunca desbloquear una segunda creación por simple visita.

### G08-AUD-006 — BLOQUEO DE ALCANCE, no defecto

El proveedor es una clase privada en memoria que devuelve una sesión inventada. El módulo no importa ni registra SDK de Stripe en producción; la respuesta `202` no devuelve un enlace de cobro y declara `payment_confirmed=false`. Por tanto **no se ha validado Stripe Test externo**, autorización por cuenta, credenciales, comportamiento de pasarela, wallets, webhooks Live/TEST ni conciliación. Ninguno de estos puntos puede inferirse de la CI sintética.

**Acción:** integrar adaptador Stripe TEST en PR independiente **solo** con autorización explícita de acceso a cuenta y modificaciones de prueba; primero cerrar G07-AUD-001/002 y aprobar G06.

## 3. Controles positivos verificados por lectura/CI

- Nuevo blueprint **no registrado** en `app.py` ni expuesto por `/pagar/<token>`; las rutas financieras legacy siguen con `@advisory_financial_prefreeze` y no hay enlace Checkout real.
- `FLASK_ENV=testing`, `current_app.testing`, bandera interna y `is_test=True` restringen la muestra; `Origin` exacto y CSRF de sesión protegen el harness dentro de su contexto.
- Total EUR en **céntimos enteros**, desglose 30 %, token opaco fuerte, vencimiento mínimo 30 min; no se acepta el `confirm` ausente/falso, ni cambio de importe.
- La reserva tiene `UNIQUE(advisory_id)`, `FOR UPDATE` y COMMIT previo al proveedor; respuesta de sesión test debe coincidir en importe, metadata y URL. Error ambiguo conserva `creating` o `uncertain`.
- Ni `quote_accepted_at` ni crear un intento confirman un pago; tampoco la URL de retorno. Los eventos futuros requerirán webhook firmado G09 y conciliación G10.

Estas garantías describen **código de la PR y pruebas controladas**, no estado de la web actual ni certificación de seguridad de un despliegue.

## 4. Pruebas de regresión de auditoría (solo ficticias)

`tests/test_s01_g07_g08_independent_audit.py` incorpora:
- **2 contratos seguros pendientes en `xfail(strict=True)`**, uno por cada hallazgo ALTO: no son «PASS de seguridad». Si se reparan, se deben quitar los `xfail`, no desactivarlos.
- Prueba positiva de que `app.py` no registra el blueprint y PREFREEZE permanece.
- Prueba positiva de que el proveedor utilizado es una implementación puramente in-process.

Para el próximo cambio, la salida de CI deberá distinguir **passed**, **skipped** y **xfailed**: CI verde **con 2 xfailed no cierra AUD-001 ni AUD-002**.

## 5. Propuesta de orden

| Prioridad | Entrega | Criterio de aceptación |
| --- | --- | --- |
| **P1** | Remediación G07-AUD-001/002 **en rama independiente** | Invariante de aceptación dentro de reserva; mismo COMMIT consentimiento+intento; fallo antes de commit sin huérfano y después de commit conserva intento bloqueado; pruebas PG18 de carrera |
| **P2** | G06 + auditoría del consentimiento y UX | Términos, importe final, identidad, hash de versión y recuperación sin reintento financiero |
| **P3** | Revisión independiente del código remediado | Cero XFAIL en controles ALTO, resultados CI sobre SHA exacto, diferencias con #50 revisadas |
| **P4** | Stripe Test **externo**, solo con permiso separado | Adaptador, eventos firmados, webhooks y reconciliación supervisada en entorno aislado; jamás pasar de Test a Live por flag |

**Decisión vigente: NO-GO** para merge/despliegue/exposición de G07/G08 y para cobros reales. Se permite continuar con **implementación y pruebas locales/sintéticas** de las remediaciones, en otra PR y sin alterar #50.

## 6. Límites de revisión

Esta auditoría lee el código GitHub de PR #50 y utiliza pruebas ficticias SQLite. **No** se ha auditado el navegador real de un formulario público (no existe), no se ha probado PG18 dos procesos para la nueva ruta, no se ha leído Railway ni tablas actuales, no se ha usado Stripe TEST ni Live. La contabilidad/IVA, destinatario del cobro y payout MERU permanecen en G06/G13. El hecho declarado por el propietario de que nunca hubo cobros PayPal en la web y el inventario local histórico de seis expedientes / cero señales no afectan a estas conclusiones.
