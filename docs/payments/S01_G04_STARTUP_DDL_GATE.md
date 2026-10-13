# S01 · G04 — Eliminar DDL del arranque web y verificar esquema en solo lectura

**13/10/2026 · PR en borrador, APILADA sobre #45 `9086bee60b52d0cde269ad06bb8388b60125873c`.**

**NO MERGE · NO DEPLOY · NO CAMBIO EN RAILWAY · NO MIGRACIONES PRODUCTIVAS · NO PAGOS.**

## Amenaza y causa

- `app.py` importaba el modelo SQLAlchemy, ejecutaba **`db.create_all()`** y varios `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` desde un `try: ... except Exception: pass`. La importación sucedía en **Gunicorn** y **en `bootstrap_db.py` antes de consultar Alembic**.
- El `Procfile` ejecutaba `python bootstrap_db.py && gunicorn ...`, por lo que cada despliegue podía comenzar aplicando DDL aunque ningún operador hubiese autorizado una migración.
- El ensayo de restauración en el Mac mini de #45 terminó **PASS** bajo código anterior, demostrando compatibilidad de las tres migraciones S01 pero no imposibilidad de DDL anticipado. Esta rama **cambia intencionadamente** el comportamiento del arranque; deberá ensayarse de nuevo sobre copia aislada.
- El riesgo es de despliegue **futuro**, no evidencia de corrupción actual.

## Corrección propuesta

1. Eliminar íntegramente el bloque de `db.create_all`/ALTER de `app.py`. La importación del módulo Flask **no debe ejecutar DDL**. La funcionalidad de login, FIFO y asesoramiento no se toca.
2. Reemplazar `Procfile: python bootstrap_db.py` por `python startup_schema_gate.py`: **antes de arrancar Gunicorn se ejecuta un gate de inspección, no una migración**. Ante cualquier discrepancia termina con exit 1 y no abre servicio.
3. `startup_schema_gate.py` inspecciona en una transacción PostgreSQL **READ ONLY** (con rollback) que el repositorio tenga un único Alembic head S01, que la BD ya esté **exactamente** en `z9a0b1c2d3e4`, que existan tablas y columnas de los modelos, y que constraints e índices críticos de S01 estén presentes. **No crea, rellena, borra, actualiza ni repara tablas; no hace stamp ni upgrade.** SQLAlchemy/conexión fallidos producen una salida genérica, sin traceback ni DSN.
4. `bootstrap_db.py` permanece como **entrada administrativa explícita**, no invocada por el servidor. Solo ejecuta `db.create_all()` tras detectar **cero tablas** en un PostgreSQL nuevo; después valida que la estructura recién generada esté íntegra y vacía, estampa el último baseline histórico y ejecuta migraciones de datos. Sobre una BD versionada ejecuta Alembic explícito. Sobre esquema parcial, poblado y sin Alembic falla sin repararlo.
5. Pruebas aisladas PG18 cambian el contrato: importación sobre BD vacía deja **cero tablas**; gate de arranque rechaza antes de DDL; `bootstrap_db.py` manual crea schema y semillas; gate acepta versión correcta sin mutaciones; versiones obsoletas, esquema parcial y constraint financiero faltante son bloqueados y no reparados. Pruebas estáticas preservan estas barreras.

## Cambio operativo intencionado — NO apto para desplegar aisladamente

**El primer arranque de un entorno nuevo queda bloqueado por diseño hasta ejecutar su inicialización explícita**. **Un deploy sobre una BD productiva con la revisión anterior también debe fallar**; no intentar recuperar sustituyendo el Procfile por el antiguo. No tocar Railway hasta disponer de:

- Revisión independiente del diff acumulado S01 y plan explícito de corte / retirada de procesos anteriores.
- Consulta de metadatos aprobada de `alembic_version`, existencia de tablas/constraints y respaldo actualizado verificable; no abrir ni importar datos personales en CI/chat.
- Un operador y ventana autorizada para ejecutar **exactamente** el comando administrativo `bootstrap_db.py`, con credenciales y DB objetivo verificadas **por una autoridad operativa independiente**, sin otros procesos que puedan crear/alterar esquema ni cobrar; reglas de aborto ante cualquier drift.
- Ensayo actualizado sobre copia restaurada intacta del Mac: pre/post, recuentos e integridad histórica y doble arranque del gate/Flask bajo nuevas barreras.
- Estrategia de recuperación que no borre el historial financiero; jamás bajar o borrar tablas S01 ni volver a endpoints PayPal/U03 capaces de cobrar.

### Límites del gate

- El gate comprueba que existe un esquema aprobado, no que una migración previa fuera segura ni que no haya operaciones PayPal pendientes o pagos reales habilitados.
- Comprueba modelo, revisiones, constraints e índices S01, **no una igualdad byte a byte de todas las tablas y todas las constraints de la BD histórica**. Revisión independiente debe validar drift global si aparece.
- En un sistema con múltiples réplicas, **un gate por worker no coordina cortes, locks, migraciones ni actividad concurrente**. Se necesita una ventana administrativa y procedimiento de despliegue externo.
- Un fallo de gate **deja el servicio no disponible** en vez de reparar esquema: esto es la protección deliberada.
- **El gate apunta al head S01 de este árbol**; cuando un cambio autorizado añada una revisión deberá actualizar el head exigido y sus tests. Nunca intentar stamp para silenciar discrepancias.

## Ensayo local ampliado desde backup previo — pendiente de ejecución

La herramienta heredada de PR #45 `tools/s01_rehearse_restored_backup.py` se amplía
**solo en esta rama** para que, tras restaurar una copia PGDMP privada en PostgreSQL
18 aislado por Unix socket:

1. Importe la aplicación Flask bajo el guard de red y vuelva a comparar
   recuentos y huellas de **todas las tablas/columnas históricas** con el
   estado anterior al import. Exija que `alembic_version` siga en el head viejo.
2. Ejecute `bootstrap_db.py` **explícitamente**, nunca por `Procfile`, sobre
   el clon local; valide las migraciones S01.
3. Ejecute `startup_schema_gate.py` de modo READ ONLY tras la primera
   migración y nuevamente tras la segunda ejecución idempotente; cada vez
   verifique conservación de filas y constraints.
4. Informe solo contadores técnicos `S01 G04 IMPORT` y
   `S01 G04 STARTUP 1/2`, **sin mostrar datos, hashes, logs ni DSN**.
   Ningún archivo original debe modificarse, subirse ni utilizarse para
   conexiones externas.

Esta ampliación exige una **nueva ejecución local** en el Mac antes de
declarar superado G04 sobre copia restaurada. La evidencia R01/S01 anterior
solo cubría el bootstrap antiguo; no puede certificarse G04 mediante su
PASS histórico.

## Criterio de aceptación de esta PR

- CI: backend, PostgreSQL 18 y browser, **sobre SHA final exacto**; nuevas pruebas fail-closed sin saltos.
- Repetir ensayo con copia local de producción **sin exponer contenido ni hashes de datos** para validar el cambio de arquitectura contra la estructura histórica.
- Revisión independiente y autorización posterior separada para integrar el cambio.
- Cualquier fallo, estructura parcial, constraint ausente, head diverso, falta de pruebas o incapacidad de plan de rollback: **NO-GO**.

**La PR no modifica cuentas, variables, credenciales, PayPal, Stripe, MERU, Railway, datos reales, facturas ni pagos.** Rafa seguirá encargándose de la facturación fuera de la aplicación.


## Evidencia del Mac — primer G04 real: NO-GO en gate tras upgrade (13/10/2026)

El propietario ejecutó el ensayo sobre el respaldo PGDMP original de 10/10
usando SHA `7a718659d47be24536ddfb8cb5a62e30b87fa612` y obtuvo:

```text
S01 G04: commit validado
S01 PRECHECK: backup privado, formato custom, SHA-256 y PG18 OK
S01 RESTORE: copia restaurada y revisión inicial OK
S01 G04 IMPORT: sin cambios en esquema ni historial OK
S01 REHEARSAL: NO-GO: Gate de arranque READ ONLY pasada 1: fallo (código 1)
```

El gate mostró únicamente un error genérico, de modo que el diagnóstico
concreto **no quedó confirmado por el Mac**. Revisión del código detectó una
**incompatibilidad objetiva, causa probable**: el gate requiere los nombres
`ck_s01_attempt_amount` y `ck_s01_attempt_currency`, mientras que la
migración S01 anterior definía esas dos restricciones CHECK sin nombre. Las
pruebas anteriores creaban la tabla vía ORM `create_all()`, que sí nombraba
esas constraints. El cambio G04 elimina ese DDL, de forma que sobre una
restauración histórica el Alembic ejecuta el `CREATE TABLE` directamente.

**Remediación propuesta en esta misma PR**:
- Nombrar expresamente ambas CHECK en
  `y8z9a0b1c2d3_s01_checkout_attempts.py`, sin relajar el gate.
- Añadir regresión SQL sobre PG18 y tabla legacy sintética sin importar Flask
  que consulte `pg_constraint` y exija esos tres CHECK con sus nombres.
- En un nuevo fallo del gate, permitir que el ensayo local imprima **solo una
  etiqueta fija** `S01 G04 CAUSA: GRAPH|TABLES|REVISION|COLUMNS|
  ADVISORY_COLUMNS|CONSTRAINTS|INDEXES|READONLY|DATABASE|CHECK|INTERNAL`.
  No extraer trazas, DSN, datos, filas, archivos o contenido del respaldo.

**Resultado G04 real anterior: NO-GO, no se reinterpreta como PASS.**
Tras CI sobre el commit corregido se requiere un **nuevo ensayo local completo**
que acredite `S01 G04 STARTUP 1/2` y `S01 REHEARSAL: PASS`. Ante otro
NO-GO, detener y revisar el código seguro antes de proceder a producción.

