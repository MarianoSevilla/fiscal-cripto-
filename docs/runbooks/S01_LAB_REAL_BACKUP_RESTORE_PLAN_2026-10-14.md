# STG-B10J — Plan autorizado por fases para comprobar una copia REAL de S01 LAB

**Estado:** PROCEDIMIENTO PREPARADO, **NO EJECUTADO**. Fecha de elaboración: 14/10/2026. Esta documentación no autoriza ejecutar PostgreSQL DDL, crear/adjuntar/restaurar volúmenes Railway, descargar una copia con información real, ni modificar producción/staging.

## 1. Pruebas verificadas antes de este plan

- PostgreSQL `railway`, versión 18.6 (server_version_num `180006`) y huella `7696213098351943739` coinciden **desde dos orígenes**: lectura del propietario en la consola de Postgres y ejecución privada de solo lectura `s01-lab-maintenance`, deployment `86336018-9964-471b-92c7-e4b40db8e4e1`.
- Preflight de esquema vacío (public y otras categorías de catálogos) PASS en la ejecución anterior, sin DDL, migraciones, emails ni pagos.
- GitHub B10I PR #72 probó `pg_dump -Fc`, hash SHA256, `pg_restore --exit-on-error` y comparación de esquema/datos **solo con dos clústeres PostgreSQL18 sintéticos**. CI `38543045211` SUCCESS.
- La presente B10J añade pruebas negativas y estructura de evidencia. Incluso si dan PASS, **no prueban** todavía ninguna copia del volumen S01 real.

## 2. Identidades inmutables del origen real

- Railway project S01: `5f26aa6e-2e6d-46ef-bb5f-bca4ece07d5e`.
- Environment lab: `3f9758ef-4e26-4e8d-9dd4-7b9286d81ea8`.
- Postgres source service: `f680f3fc-4581-44ff-8bc1-d034840f2c7e`.
- Postgres source volume: `c35d178f-7473-4d0b-adb9-1faae815b7af` (mount `/var/lib/postgresql/data`).
- DB `railway`, PG18, system identifier `7696213098351943739`.
- Maintenance service: `9728d19b-7d17-4acb-8be1-c4b0847179df`; solo comando readonly `python -u private_maintenance_identity.py`, commit anclado `2062109d900281f383bc1f3a5c94a98be7140d62` en el último despliegue, `restartPolicyType=NEVER`, sin cron ni dominios/proxies públicos.
- Web S01 lab: `212f4f52-b349-4387-a046-9f6b08237d2e`, aún sin despliegue.

## 3. Puertas previas a **extraer un backup real**

1. Autorización explícita del propietario para lectura/extracción de backup real, alcance, almacenamiento y vencimiento; es un permiso diferente del previo permiso de huella readonly.
2. Confirmar el servicio Postgres original, volumen, estado, base, versión y huella mediante lecturas independientes. Si cambia el identificador del clúster o la procedencia del servicio, STOP.
3. Preparar ejecutor de copia efímero **separado del mantenedor de huella y del futuro ejecutor DDL**, con el rol y permisos de lectura suficientes, sin código Flask, modelos, providers, rutas HTTP, listener, cron, reintentos ni escritor SQL.
4. Asegurar que **no se usa `pg_dump` para alterar datos**, ni se crea el dump en el mismo volumen del Postgres origen; guardar un archivo `pg_dump -Fc` en destino restringido fuera del volumen original, preferiblemente cifrado en tránsito y reposo. Nunca añadir backup, credenciales, tablas de usuarios ni DSN a GitHub, CI, logs o conversación.
5. Verificar tamaño, checksums SHA256, formato y finalización sin error, registrar fecha y destino con acceso limitado. El mero archivo y checksum no son prueba de restaurabilidad.

## 4. Destino de recuperación y ensayo REAL, siempre aislados

1. Autorización específica para crear **un servicio PostgreSQL18 nuevo** y volumen nuevo en el proyecto S01 o proyecto de recuperación separado. Debe estar en entorno aislado, sin referencias de la web, sin público/TCP proxies y sin conexión con producción. Anotar ID propio de servicio y volumen: **distintos** de los originales.
2. Comprobar con `pg_control_system().system_identifier` que el destino es otro clúster, no `7696213098351943739`; destino `railway` vacío antes de importar.
3. Confirmar nuevamente un hash idéntico del artefacto antes de restaurar. Ejecutar `pg_restore --exit-on-error --no-owner --no-acl` sobre **el destino nuevo solamente**, bajo un proceso de una sola ejecución. En caso de error NO marcar recuperación como superada y prohibir reintento automático.
4. Inspeccionar en destino versión PG18, estado de Alembic, esquemas, recuentos, índices, triggers, constraints, extensiones, tipos y funciones. **Para el origen S01 actualmente vacío**, esperar que el destino reproduzca fielmente esa ausencia de objetos, en lugar de aplicar el postcheck de un esquema ya inicializado.
5. Registrar únicamente pruebas técnicas sin contenido personal. Exigir evidencias reproducibles de checksum, ID origen/destino, huellas, salida exitosa del `pg_restore` y consultas de post-verificación.
6. Retirar capacidad de ejecutar/copiar restauraciones y restringir/eliminar el respaldo de forma explícita y segura **solo bajo autorización**. No usar el botón Restore de volumen sobre el Postgres original.

## 5. Evidencia offline STG-B10J

`private_restore_evidence_gate.py` comprueba **coherencia formal, no autenticidad** de metadatos: proyecto/origen exacto, volumen y huella original, digest SHA256, relación backup/origen, destino distinto, ausencia de códigos de error y validaciones de tablas/contenidos. Los valores positivos de un registro pueden ser inventados y **no prueban** que Railway haya restaurado nada: exigir constatación independiente, nunca marcar automáticamente GO.

Su comando `main()` está cerrado, sale con `NO-GO` siempre. No abre conexiones ni procesa dumps.

## Resultado de STG-B10J en CI

- GitHub Actions [#38544630254](https://github.com/MarianoSevilla/fiscal-cripto-/actions/runs/38544630254): **SUCCESS**; 15 contratos sintéticos y dos contenedores PostgreSQL18 desechables.
- `pg_dump -Fc` sobre base fuente sintética: archivo generado; comprobación `valid-synthetic.dump: OK` por SHA256.
- Se generó una copia truncada deliberadamente. `pg_restore --list` y `pg_restore --exit-on-error` devolvieron fallo obligatorio; destino continuó sin relaciones en `public`.
- Mensaje CI: `B10J PASS: broken pg_dump rejected, exit status nonzero; disposable target intact`.
- Esta prueba es evidencia de comportamiento frente a un **archivo deliberadamente truncado**, no de tolerancia a toda clase de corrupciones posibles.
- La validación `private_restore_evidence_gate.py` es estrictamente formal: **ningún registro manual constituye una prueba autónoma de que un backup real exista o haya sido restaurado**. Exigir evidencia independiente de infraestructura y consultas.

## 6. Autorizaciones y recuperación ante fallos

**Puerta 1 — lectura/extracción:** la autorización de un backup real permite únicamente su creación/copia segura, NO servicios nuevos, restauración ni cambios del origen.

**Puerta 2 — destino y restauración:** autorización distinta para el servicio/volumen nuevo y operación `pg_restore` allí. Verificación de ID propio y huella independiente, backup íntegro; abortar si no se cumplen todos los requisitos.

**Puerta 3 — DDL para inicializar S01 lab:** únicamente después de haber demostrado una recuperación real y revisado el ejecutor de mantenimiento específico, se solicitará autorización que incluya SHA y destino exactos. No confundirse con autorización para el ensayo.

**STOP absoluto:** ninguna operación sobre `main`, producción/staging, el volumen fuente, el ejecutor web, PayPal/Stripe, Resend u otros proveedores; sin merge de PR ni despliegue web.

## Documentación pública Railway

- https://docs.railway.com/guides/postgres-backups-restores
- https://docs.railway.com/volumes/backups

**Nota:** esta integración Railway solo permite ver el inventario y gestionar servicios/volúmenes; no ofrece una operación autorizada para descargar backups de volumen ni restaurarlos sin riesgo. No suplir ese límite con conexiones externas no auditadas.
