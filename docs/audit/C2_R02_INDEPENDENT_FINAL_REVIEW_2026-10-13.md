# C2-R02 — Revisión de seguridad y regresión posterior · 13/10/2026

**Dictamen de esta revisión:** **GO TÉCNICO LIMITADO** para los dos hallazgos C2-F01 y C2-F02 en entorno ficticio; **NO-GO** para fusionar PR, migrar o desplegar.

## Identificadores y fuentes

- Repositorio: `MarianoSevilla/fiscal-cripto-`. GitHub `main`: `56882073295faae3bd1bc3632288a970acb330da`, sin cambios en esta auditoría (no es una consulta de Railway).
- PR #57: base de #58, SHA `3945a97eac76451579c95e90fe571bbdf1f7c05e`. PR #58: SHA final `74bea12848aa53e05a653cec8802a7b675819da0`, **draft y sin merge**.
- Diff exclusivamente C2-R02: **5 commits, 7 archivos**: `app.py`, tres HTML, `.github/workflows/required-ci.yml`, un E2E Chromium y un documento. No nuevas migraciones, modelos, rutas Stripe Checkout ni código ejecutable de PayPal.
- [CI #87](https://github.com/MarianoSevilla/fiscal-cripto-/actions/runs/38418190182): **SUCCESS** exacto `74bea12848aa53e05a653cec8802a7b675819da0`. Backend **1.556 passed / 63 skipped**; PostgreSQL 18 bootstrap, Alembic lineal, G04 y concurrencia C2-R01 **PASS**; browser **PASS**.
- Log del E2E: `S01 C2-R02 browser E2E: 26 synthetic mobile/desktop checks PASS; roles, CSRF, notes, states, historic evidence, suspended prices/payment routes PASS; no external/provider I/O`.
- Primera ejecución #38417740980 detectó un **500 reproducido** por `make_response` no importado en URL legacy. El cambio de respuesta a `send_from_directory(...)` con `status_code = 503` corrige la causa; CI #87, **no** la primera ejecución, es el criterio de aceptación.

## Hallazgo C2-F01 — CERRADO para C1

- `static/asesoramiento-fiscal.html`: elimina promesa de respuesta de 2–3 días hábiles y avisa suspensión de presupuestos y pagos.
- `static/asesoramiento-confirmado.html`: sustituye falsa afirmación de pago y contratación por aviso explícito de URL histórica; sin enlaces activos de cobro.
- `app.py` GET `/asesoramiento-fiscal-confirmado`: documento informativo **HTTP 503, `Cache-Control: no-store`**. No prueba ausencia de operaciones históricas; evita afirmar un pago por visitar un enlace.
- `static/admin-asesoramiento.html`: elimina prioridades que presuponían presupuesto/pago pendientes e introduce layout móvil de lista seguida de ficha. Conserva las etiquetas de los estados financieros históricos para consulta, sin permitir operaciones sobre ellos.
- El endpoint `/api/asesoramiento/precios` permanece 503 y sin importes por C2-R01; formulario de nueva solicitud sigue abierto.
- Límite: cambios de contenido y pantalla; no es un dictamen jurídico del texto ni una auditoría UX completa de toda la web.

## Hallazgo C2-F02 — CERRADO para el recorrido sintético probado

El E2E `qa_s01_c2_r02_browser.py` usa Flask real por loopback, SQLite temporal, cookies de sesión genuinas, usuarios `@example.invalid` y Chromium a **375 y 1280 px**. La salida a emails/proveedores se intercepta; navegación browser fuera de loopback se bloquea.

Verifica: información pública suspendida; URL legacy 503; formulario y checkbox de interfaz; persistencia de solicitud sin importe ni token; controles de rol usuario/asesor/admin; token CSRF, rechazo sin token; nota y cambio de estado; firma de auditoría; expediente histórico ficticio con `paypal_order_id` protegido; rechazo HTTP 503 en rutas antiguas de presupuesto, mensaje y pago; botones de borrado/marca test deshabilitados. Prueba de navegación responsive general y PREFREEZE preexistentes siguen en verde.

**Límites de esta garantía:** no ha probado PayPal/Stripe/MERU ni facturación real; SQLite no reemplaza PG18 para cargas generales, pero el job PG18 conserva el test multiproceso de estado C2-R01. E2E verifica 375/1280 y no es una matriz exhaustiva de todos los tamaños y navegadores. El checkbox visual no constituye por sí solo evidencia jurídica almacenada (C2-06). No verifica estado actual de producción ni configuración Railway.

## Dependencias y exclusiones verificadas

- La cabeza #58 está **82 commits por delante y 0 por detrás de `main`**, con **75 archivos** cambiados. Está en una cadena acumulativa, **no** es un parche aislado de siete archivos contra `main`.
- La secuencia de commits contiene S01 de #33–#41, correcciones #43–#45, G04 #49, contratos sintéticos/auditorías de código #50–#53 y C1/C2 #56–#58.
- La migración propuesta por PayPal U04 #29 `w6x7y8z9a0b1` **no figura** en árbol final; el head único S01 esperado es `z9a0b1c2d3e4`. El diseño de reparto de procesamiento Stripe Connect **50/50** de PR #54 también queda fuera por decisión del propietario.
- Otras PR desde `main` (#29–#32), las ramas laterales de auditoría/evidencia (#42, #46–#48, #55) y el diseño #54 **no deben fusionarse automáticamente** junto a la cabeza acumulativa. Aunque algunas soluciones equivalentes estén en la cadena (PREFREEZE y firma Stripe), sus heads alternativos no forman parte de ella.
- La PR #47 documenta copia privada del 10/10/2026 con seis solicitudes y cero señales PayPal reportadas por el propietario, pero su inventario fuera de la línea principal no certifica el estado actual de BD ni el proveedor.

## Riesgos y condiciones no cerrados

**G04 — CRÍTICO OPERACIONAL:** el nuevo `Procfile` ejecuta `startup_schema_gate.py` antes de Gunicorn, y exige PostgreSQL con Alembic exacto `z9a0b1c2d3e4`, tablas, checks e índices. Sobre base antigua falla cerrado y puede dejar servicio fuera de línea. El segundo ensayo privado de copia restaurada **PASS fue reportado por el propietario en PR #49**, no auditado contra base viva. Requiere plan de corte, backup fresco, comprobación de esquema actual, migración administrada autorizada y recuperación segura.

**G05 — CIERRE CONDICIONAL:** antes de la puesta en producción, una consulta *agregada, limitada y expresamente autorizada de solo lectura* debe contrastar historial financiero S01 actual con la copia del 10/10/2026 y la declaración del propietario de no haber cobrado por PayPal. No exigir por defecto extractos de todas las cuentas; si aparecen datos contradictorios o intentos de estado incierto, escalar a conciliación dirigida y mantener el bloqueo.

**C2-06 — PRIVACIDAD:** verificar el texto mostrado, la base de legitimación y la necesidad/forma de evidencia de información de solicitudes; sin inventar aceptaciones o recopilar PII por defecto. **C2-F03 — SEMÁNTICA:** valorar `under_review → submitted` y token después de reautenticación, sin afirmar riesgo financiero demostrado.

**Integración/reversión:** `main` podría tener auto-deploy; fusionar sin preparar esquema puede causar indisponibilidad. Revertir a la versión antigua puede recuperar endpoints financieros antiguos y no es rollback seguro por defecto. Mantener contención económica y datos históricos a través de toda recuperación.

## Dictamen

**C2-R02 revisada: cierre técnico de C2-F01/F02, sin hallazgos bloqueantes nuevos en sus siete archivos propios dentro del contrato C1.** No constituye auditoría externa ni certificación de producción. **PR #58 debe seguir DRAFT; no merge, no deploy, no migración** hasta gate de integración y autorización posterior individualizada. Documento complementario: `docs/audit/S01_INTEGRATION_SEQUENCE_PRE_REDESIGN_2026-10-13.md`.
