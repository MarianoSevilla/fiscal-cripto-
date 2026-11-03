# SEC5-PRIV — Recuperación operativa segura de backups manuales

**Fecha de corte:** 03/11/2026. **Estado:** procedimiento de control y decisión; **NO es autorización de restauración ni certificación de copias**. **Propósito:** impedir que una restauración reexponga datos suprimidos/bloqueados, omita evidencia financiera o abra la web antes de completar las comprobaciones.

## 1. Evidencia real frente a lo no acreditado

| Elemento | Evidencia comprobada | Limitación |
| --- | --- | --- |
| Código productivo | `main@10be520edeb0f2090f71939192d6d1738afd1c19`, PR #183 fusionada; esquema y Alembic inspeccionados al arrancar mediante `startup_schema_gate.py`; `Procfile` ejecuta este gate antes de Gunicorn | **No hay gate de decisiones de privacidad en el arranque**. El gate actual no impide exposición de datos restaurados tras una supresión |
| Railway | Web y PostgreSQL 18 desplegados con estado `SUCCESS`, commit web coincidente con `main` a 03/11/2026; volumen PostgreSQL de 5.000 MB; sin volumen web, sin buckets visibles en el entorno ni cambios staged | El conector **no acredita si están configurados backups de volumen**; comprobar manualmente la pestaña *Backups* del servicio PostgreSQL. Ningún backup queda demostrado por el estado SUCCESS |
| Copias manuales | En documentación previa constan respaldos `pg_dump` cifrados con `age` (11/10 y 14/10) y restauraciones locales históricas; el titular comunicó copia posterior y prueba de restauración estructural PostgreSQL 18 el 01–02/11 | **Actualización 03/11/2026:** el titular ejecutó controles locales en su Mac y comunicó tres copias cifradas y una restauración estructural satisfactoria de la más reciente; consultar §5. La verificación del origen independiente y antigüedad del checksum, la hora de corte real, el contenido completo y los cambios posteriores siguen sin acreditarse |
| CI de privacidad | PR #181 (aislamiento), #182 (replay tras `pg_restore`) y #183 (evidencia externa con huella independiente): pruebas sintéticas PostgreSQL 18 con CI completa | **No existe almacén externo duradero ni índice confiable completo de decisiones reales**. El ensayo no es una restauración real ni bloqueo jurídico |
| Datos de terceros | El ORM tiene 17 tablas; hay solicitudes S01, referencias financieras, correos copiados sin FK y registros de soporte | Un informe de cuentas o `user_id` aislado no acredita inventario completo de sujetos o proveedores |

**Dictamen actual:** continuidad del servicio **actual** sin cambios por esta revisión. La aptitud para **restaurar una copia antigua y reabrir tráfico es NO-GO / NO VERIFICADA**, hasta reunir las evidencias y autorización específicas de los apartados siguientes.

## 2. Preflight sin leer datos personales ni escribir en sistemas productivos

Responsable: titular, en su Mac, con verificación de metadatos exclusivamente. No enviar copia, claves `age`, hashes privados, rutas de equipo, logs, pantallazos de datos o archivos descifrados al chat, GitHub, Railway ni CI.

1. **Identidad del respaldo:** anotar en un registro local privado el identificador, ubicación fuera de Railway, fecha **real de finalización** del `pg_dump` (no inferirla del nombre), si es `.dump.age` cifrado o `.dump` en custom `PGDMP`, tamaño, propietario, permisos y existencia de copia adicional aislada. No descomprimir ni desencriptar por esta revisión.
2. **Integridad y procedencia:** contrastar el SHA-256 del archivo cifrado con una referencia conservada **antes** del ensayo y bajo custodia separada. Un hash calculado ahora permite futuras comparaciones, pero **no prueba autenticidad histórica**. Para validar la estructura `PGDMP` de un archivo cifrado se necesita descifrarlo en un entorno privado, en una fase separada y autorizada. Ausencia de hash anterior = evidencia de integridad histórica insuficiente, no PASS.
3. **Estado del servidor:** confirmar por lectura el último despliegue `main`, versión PG18, ubicación de volumen, si existen backups Railway visibles con fechas y cobertura, y si existe otro mecanismo de respaldo independiente. El estado de un volumen de producción no equivale a backup.
4. **Punto de corte:** identificar la hora del respaldo, qué altas, bajas, solicitudes, correcciones de datos, cambios de privilegios, pagos, reembolsos, reclamaciones y decisiones de bloqueo/supresión pueden haber ocurrido **después**. Si no hay evidencia suficiente, declarar el intervalo **desconocido**. Nunca asumir «no hubo cambios» porque la actividad haya sido baja.
5. **Evidencia externa de privacidad:** localizar un registro **independiente del backup**, restringido, completo hasta el instante de corte y con referencia confiable frente a versiones antiguas. **No existe todavía evidencia de uno productivo**. El archivo sintético de PR #183 y sus huellas no sirven para acreditar decisiones reales. Si falta o no puede certificarse su actualidad/completitud, es **NO-GO para reabrir con datos antiguos**.

**Salida del preflight:** únicamente `RESPALDO_IDENTIFICADO=SI/NO`, `FECHA_DE_CORTE_CONFIRMADA=SI/NO`, `INTEGRIDAD_PREVIA=SI/NO`, `RESTAURACION_ACTUAL_PROBADA=SI/NO`, `DECISIONES_POSTERIORES_CONCILIADAS=SI/NO`. Nada de datos personales, rutas privadas, identificadores de clientes ni SQL de filas.

## 3. Criterios de restauración offline (solo en una fase posterior autorizada)

Esta sección **no ordena ejecutar comandos ahora**.

1. **Preservar producción y evidencia actual.** No reemplazar `DATABASE_URL`, ni seleccionar *Restore* en Railway, ni parar el servicio vigente, ni alterar roles/credenciales. Un ensayo debe realizarse con PostgreSQL 18 **local, efímero, aislado de la red y del servicio real**, previa comprobación de espacio en disco. Si se necesita recuperación productiva se diseña y autoriza expresamente otra operación.
2. **Descifrar solo en el Mac aislado** cuando corresponda; comprobar el checksum previo y la cabecera custom, y restaurar en una **base nueva de prueba**, con `pg_restore --single-transaction --exit-on-error`. Nunca hacerlo sobre la base actual. Usar como referencia el procedimiento histórico `docs/payments/S01_OFFLINE_PRODUCTION_BACKUP_REHEARSAL.md`; su herramienta `s01_rehearse_restored_backup.py` verifica la migración **histórica S01** (espera revisión anterior `v5w6x7y8z9a0`), **no sirve para certificar automáticamente un dump reciente ya migrado**. <https://www.postgresql.org/docs/18/app-pgrestore.html>
3. **Contraste estructural y funcional en aislamiento:** PostgreSQL 18; esquema esperado de las 17 tablas ORM y dependencias físicas; Alembic en revisión `z9a0b1c2d3e4` si se ensaya contra `main` actual; constraints e índices S01; recuentos agregados internos, integridad de relaciones, roles y separación de privilegios. No imprimir filas, correos, hashes de filas o documentación profesional. `/healthz=200` no sustituye este contraste.
4. **Diferencias posteriores al backup:** reconstruir de fuentes justificadas el conjunto de cambios que el backup antiguo **perdería**, incluidos pagos/Stripe, reembolsos, derechos de acceso, incidencias, consentimientos, derechos RGPD y eventuales decisiones de supresión/bloqueo. La restauración de un respaldo viejo no puede presumirse que contiene esos eventos.
5. **Reconciliar por expediente y finalidad:** comprobar identidad inequívoca por ID verificado, no por email copiado; estado financiero y custodia de terceros. No aplicar un borrado masivo ni destruir evidencias sujetas a conservación. Si proceden bloqueos, acreditar aislamiento frente a rol ordinario y accesos excepcionales y posterior recuperación. Rechazar un manifiesto perdido, truncado, alterado, no vinculado al backup o no actualizado.
6. **Probar la barrera antes de apertura:** el procedimiento debe demostrar que la restauración **sigue sin tráfico** mientras no existan decisiones y reconciliación completas. Los ensayos #182/#183 solo lo prueban en CI; `startup_schema_gate.py` y `Procfile` **no implementan esta barrera productiva**.
7. **Documento de aceptación:** acta sin datos personales con identificador de backup, procedencia, periodo cubierto, prueba de integridad, revisión de estructura, decisiones posteriores y excepciones, responsable, fecha y resultado `GO/NO-GO`. Un PASS técnico de `pg_restore` no es GO final.

## 4. Matriz de decisión: mantener sin tráfico / NO-GO

| Hallazgo | Decisión |
| --- | --- |
| No hay copia localizable o no se conoce la fecha de corte | **NO-GO**; conservar producción actual, evaluar recuperación alternativa sin alterar datos |
| Copia íntegra pero no restaurada con éxito en entorno aislado actual | **NO-GO** para sustitución o reapertura; programar ensayo offline específico |
| Copia restaurable pero sin registro externo **completo, auténtico y actual** de decisiones posteriores, o sin manera de reconstruirlas | **NO-GO** para exponer datos restaurados; mantener servicio restaurado desconectado y analizar caso |
| Decisión de supresión/bloqueo posterior no reconciliada o titularidad incierta | **NO-GO**; revisión por expediente. No usar coincidencia de email para decidir |
| Incertidumbre financiera, consentimientos, pagos, reclamaciones o custodia de Rafael | **NO-GO** en el ámbito afectado; escalar y preservar integridad, sin borrados improvisados |
| Un ensayo restauró datos y pasó esquema pero no existe puerta de privacidad en Flask | **NO-GO** para reapertura automática; exigir control operativo independiente y verificación |
| Todo validado en aislamiento y decisiones conciliadas | **Candidato a GO**, nunca autorización implícita: requiere plan de corte, copia contemporánea, comprobación posterior y **consentimiento explícito del titular** para alterar producción |

**Regla de seguridad:** una copia anterior puede devolver a visibilidad datos que un usuario había pedido suprimir. Mantener restauración fuera de tráfico hasta aclarar y resolver el conjunto de decisiones. **No detener preventivamente la web actual por el mero hecho de tener copias antiguas**.

## 5. Trabajo concluido / trabajo no verificado

**Terminado en esta revisión:** inventario read-only de GitHub/Railway, análisis de procedimientos históricos, criterios de preflight, conciliación y GO/NO-GO, sin acceso remoto a datos reales. **Prueba local comunicada por el titular (03/11/2026):** encontró tres archivos `*.dump.age` en su Mac; la copia más reciente tenía mtime `2026-11-01T23:49`, tamaño aproximado de 0,14 MB y permisos privados. Su checksum lateral coincidió; el descifrado `age` y `pg_restore --list` pasaron. Después ejecutó un **ensayo estructural local específico**, distinto del antiguo script S01, con los siguientes resultados comunicados: `FILEVAULT: ON`, `SHA256: COINCIDE`, `CLUSTER_LOCAL_SIN_TCP: PASS`, `PG_RESTORE_TRANSACCIONAL: PASS`, `TABLAS_ORM: 17/17 PASS`, `ALEMBIC: PASS`, `RESTRICCIONES_FK: PASS`, `LIMPIEZA_TEMPORAL: PASS` y `RESULTADO: PASS_ESTRUCTURAL_LOCAL`. El código de ese script se revisó: usaba PostgreSQL 18 temporal sin conexiones TCP, paso por tubería de `age` a `pg_restore` y eliminación del clúster tras detenerlo. **Los resultados son evidencia operativa facilitada por el titular, no ejecución remota verificada de forma independiente.**

**Sin verificar:** procedencia y antigüedad de la referencia SHA-256 (coincidencia no demuestra que el checksum se custodiara antes), fecha de **finalización real** de `pg_dump` (mtime no la certifica), completitud y fidelidad de las filas/datos de negocio, consistencia financiera o datos externos, así como accesibilidad de las otras dos copias sin checksum directo. El ensayo comprobó 17 tablas **esperadas**, no un inventario completo de toda relación física; `RESTRICCIONES_FK: PASS` confirmó que no existían claves foráneas marcadas `NOT VALID`, pero no ejecutó una auditoría de todos los datos. Siguen sin acreditarse la pestaña *Backups* de Railway, un registro productivo externo completo y actual de decisiones, reconciliación posterior al corte, proveedores y barrera de arranque. No se han ejecutado operaciones sobre producción.

**Próximo punto de control:** la restauración **estructural** está comprobada mediante el ensayo local declarado, por lo que no se debe repetir sin necesidad. A partir de ahora se requiere reconstruir las decisiones de privacidad, modificaciones y eventos financieros posteriores al corte y custodiar evidencia externa antes de considerar una recuperación de producción. Cualquier restauración productiva y cambio de infraestructura exigirá autorización expresa. No subir a GitHub datos de clientes, backups, hashes de filas ni credenciales.

## Referencias

- Procedimiento local histórico: `docs/payments/S01_OFFLINE_PRODUCTION_BACKUP_REHEARSAL.md` y `fiscal_app_export/tools/s01_rehearse_restored_backup.py`.
- Ciclo de vida y restauración sintéticos: `docs/security/SEC5_PRIV_RECORD_LIFECYCLE_PG18_20261102.md`, `docs/security/SEC5_PRIV_RESTORE_RECONCILIATION_PG18_20261102.md`, `docs/security/SEC5_PRIV_EXTERNAL_EVIDENCE_20261103.md`.
- Decisiones por finalidad y derechos: `docs/security/SEC5_PRIV_POLITICA_PARA_APROBACION_20261101.md`, `docs/security/SEC5_PRIV_DERECHOS_SUPRESION_PROCEDIMIENTO.md`, `docs/security/SEC5_PRIV_CASE_REVIEW_20261102.md`.
- Docs oficiales: <https://www.postgresql.org/docs/18/app-pgrestore.html>, <https://docs.railway.com/volumes/backups>, <https://railway.com/guides/postgres-backups-restores>.
