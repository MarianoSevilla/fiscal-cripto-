# marianosevilla.com — Plan de integración S01 antes del rediseño UX/UI

**Fecha:** 13/10/2026 · **PLAN, NO ORDEN DE EJECUCIÓN**. Sin acceso/alteración de Railway, DB productiva, Stripe, PayPal, MERU, credenciales o datos reales. **Ningún merge, despliegue ni migración autorizado** con este documento.

## 1. Base, candidato y objetivo de estabilidad

- Base GitHub `main`: `56882073295faae3bd1bc3632288a970acb330da`, sin cambio. Comprobar nuevamente antes de cada operación. El SHA GitHub **no confirma por sí solo SHA desplegado realmente en Railway**.
- Candidato funcional acumulativo: head PR #58 `74bea12848aa53e05a653cec8802a7b675819da0`, **82 commits / 75 archivos por delante de `main` y 0 behind**, CI #87 SUCCESS (1.556 passed, 63 skipped; PG18 y Chromium C2-R02 en verde).
- Objetivo de la primera integración: **mantener FIFO/reportes actuales**, permitir recepción y consulta/gestión interna S01 y **suspender presupuestos, enlaces y pagos**. PayPal fuera permanentemente de S01 futuro, historial intacto. **No habilitar Stripe Connect Live ni pagos S02**.
- Prohibido saltar a rediseño Apple/UX/UI antes de cerrar una base de seguridad, esquema y release verificables. Una PR en borrador no significa cambios productivos.

## 2. Árbol de dependencias observado (NO fusionar por número)

Ruta acumulativa incluida en los 82 commits, desde `main`:

`main` → etapas S01 **#33–#41** (algunas PR intermedias tienen bases `main`, pero el árbol de #41 contiene su secuencia) → **#43** → **#44** → **#45** → **#49 (G04)** → **#50** → **#51** → **#52** → **#53** → **#56 (C1)** → **#57 (C2-R01)** → **#58 (C2-R02)**.

- No fusionar aisladamente todos esos números: sus cabezas ya están **ancestralmente incluidas** en el candidato #58. Los commits deben incorporarse **una sola vez** y conservar trazabilidad por SHA.
- **Excluidas del árbol candidato:** PR #29 (U04 motor PayPal + migración `w6x7y8z9a0b1` divergente); PR #54 (Connect 50/50 de costes obsoleto); PR #30–#32 como ramas alternativas/aislamiento; PR #42, #46–#48 y #55 como auditorías/instrumentos laterales. No cerrar ni borrar ninguna sin autorización; preservar la historia.
- La PR #47/#48 mantiene información útil G05, pero **no se fusiona automáticamente** ni se exige CSV PayPal personal completo por defecto.
- Revalidar que `main` es ancestro exacto del candidato y que el head final no contiene ni la migración PayPal divergente ni el 50/50.
- Si cualquier SHA, branch protection, estado CI o historia diverge: **STOP** y nuevo cálculo, sin rebase/cherry-pick/force para «arreglarlo» silenciosamente.

## 3. Gates por orden y responsables

| Gate | Verificación exigible | Situación 13/10 | Acción admitida ahora |
|---|---|---|---|
| C2 técnica | Python, PG18, PREFREEZE, E2E usuario/asesor C1 | PASS en CI #87 de SHA #58 | Solo lectura y documentación |
| G04 esquema | Head `z9a0b1c2d3e4` y checks, backup actual, migración aislada, gate READ ONLY | CI PASS; ensayo de backup Mac PASS reportado en #49; BD real actual desconocida | Preparar runbook, **no migrar** |
| G05 legado PayPal | Conteos actuales S01 agregados y anomalías; cotejo con backup; escalar al proveedor solo si dudas | Backup 10/10 sin señales reportado, **corte actual pendiente** | Diseñar consulta sin PII, **no ejecutarla** |
| C2-06 | Revisión de texto/legitimación y política de evidencia de solicitudes | Seguimiento jurídico | Definir criterios y responsable, no inventar aceptación |
| Staging | Deploy controlado exacto SHA, DB sintética/aislada con Alembic autorizado, no proveedores, regresión y rollback | Sin ensayo de candidato #58 | **Requiere autorización separada** |
| Producción | Control de auto-deploy, backups, migración administrada, corte, vigilancia 5xx, comparación SHA/DB, rollback | NO-GO | **Requiere autorización de integración y despliegue separada** |
| Pagos futuros | Stripe Connect contrato 30 % Rafa honorarios, procesado 30/70, refunds completos, TEST/Live | Fuera de alcance; diseño #54 50/50 descartado | No activar nada |

## 4. Secuencia operativa propuesta (pasos FUTUROS, no ejecutar)

**Fase A — Preflight sin alteraciones:** bloquear baseline y SHA, resolver discrepancias de ramas; constatar ausencia de `w6x7y8z9a0b1` y #54; inventariar endpoints financieros bloqueados y funcionalidades FIFO; confirmar servicios web/worker/staging, nombres de branches asociadas, configuración de auto-deploy de Railway mediante **lecturas autorizadas** y sin mostrar claves. Elaborar criterio de aceptación/aborto y personas responsables.

**Fase B — Evidencia actual y respaldo:** obtener autorización explícita limitada para inspección READ ONLY de metadatos/contadores anónimos (`alembic_version`, tablas/constraints y señales agregadas S01), sin identificadores, PII ni SQL completo al chat. Validar copia de seguridad **fresca** fuera del repositorio y restauración aislada; confirmar posibilidad de volver a servicio sin destruir filas financieras. G05 se cierra proporcionalmente solo si no hay anomalías o se resuelven.

**Fase C — Staging controlado:** con permiso independiente, desplegar exacto SHA candidato en staging **aislado**, con BD ficticia/restore desidentificado autorizado y revisión de migraciones/constraints. Mantener PREFREEZE en todo momento; controlar cliente web/worker y jobs, prueba E2E real staging y smoke FIFO sin enviar emails externos. Verificar explícitamente que **no existe camino activo** a órdenes/capturas PayPal, Checkout Stripe, mensajes de presupuesto o pagos. Probar fallo G04 contra esquema obsoleto y recuperación sin autofix DDL. Registrar métricas 5xx y resultado SHA.

**Fase D — Preparación de corte:** pedir permiso separado de merge e infraestructura. Si `main` despliega automáticamente, acordar y autorizar **primero** el control del disparador, para que una fusión no publique código G04 antes del upgrade de la BD. Programar ventana, drenar procesos antiguos y evitar peticiones financieras durante la transición, sin perder solicitudes; verificar baseline GitHub vs deployment actual. Designar quién ejecuta cada verificación y la orden exacta de abortar. **No se puede asumir que desactivar auto-deploy esté ya hecho**.

**Fase E — Migración/despliegue sólo bajo nuevo GO:** durante ventana controlada, usar backup fresco, verificar BD objetivo y revisión inicial; ejecutar **solo** migración administrativa aprobada del head viejo `v5w6x7y8z9a0` al nuevo `z9a0b1c2d3e4`; verificar inmediatamente constraints y datos financieros históricos con consultas agregadas. **Después** poner en servicio el aplicativo del SHA aprobado y ejecutar gate de arranque READ ONLY. Fijar versión web y worker compatibles, probar login/FIFO, recepción S01, notas/estados C1, 503 de cobros, sesiones, comunicación y salud; vigilar 4xx/5xx y errores en ventana postcorte.

**Fase F — Recuperación si NO-GO:** parar sin exponer datos ni reintentar operaciones potencialmente cobradas. **No revertir ciegamente a `main` antigua** si ello reabre PayPal u otras operaciones; no hacer downgrade Alembic, DROP, `stamp` ni restaurar backup sobre datos actuales salvo procedimiento explícito y verificado. Restaurar aplicación segura y **mantener bloqueo financiero**; preservar toda solicitud e historial durante cualquier reversión. Requerir un rollback propio validado en staging antes del corte.

**Fase G — Cierre:** tras GO expresamente registrado y monitorización, documentar SHA GitHub, SHA de deployments web/worker, Alembic, pruebas de datos, incidentes y reglas de soporte. Decidir por separado cierre/archivo de las PR obsoletas **sin borrar ramas por defecto**. Solo entonces congelar baseline estable antes de iniciar rediseño UX/UI sobre esa base.

## 5. Condiciones STOP automáticas del procedimiento futuro

Detener ante: `main` o candidato movidos; migración paralela PayPal U04; presupuesto/pago iniciado por rutas S01; cualquier orden/captura incierta; mismatch Alembic/schema; falta de constraints; restauración fallida o sin evidencia; CI roja/skips inesperados; diferencia de SHA Railway; mezcla de staging/producción; imposible bloquear despliegue automático; ausencia de rollback financiero seguro; riesgo de destruir historiales/PII. No improvisar fixes durante la ventana.

## 6. Autorizaciones futuras, cada una independiente

1. **Permiso READ ONLY** para estado real en Railway/BD y metadatos no sensibles.
2. **Permiso de staging** para una implantación y prueba controlada del candidato.
3. **Permiso separado de integración GitHub** (`main`) con control de auto-deploy ya aprobado.
4. **Permiso separado de backup/upgrade de BD productiva y despliegue**, con orden exacta, rollback y ventana.
5. Ninguno de los anteriores autoriza **activar Stripe Connect Live, cobrar, reembolsar ni modificar MERU**.

**Este documento no se ha ejecutado.** La línea candidata #58 y sus PR precedentes siguen en DRAFT, `main` intacta. La aprobación de C2-R02 es limitada a pruebas y comunicaciones; la seguridad productiva requiere los gates previos.
