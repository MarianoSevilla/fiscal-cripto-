# STG-B10H — Diagnóstico y excepción limitada de PORT (14/10/2026)

## Evidencia
La segunda ejecución real y autorizada exclusivamente para lectura del servicio `s01-lab-maintenance` (despliegue `794cdac2-17f6-4810-8386-eacb99f7540e`) mostró literalmente:

`S01 STG-B10G: NO-GO (PUBLIC_NETWORK; markers=PORT)`

El inventario Railway comprobó **cero dominios públicos, cero dominios custom y cero TCP proxies**; PostgreSQL lab estaba operativo y la web lab sin deploy. La guardia detuvo la ejecución antes de abrir la conexión PostgreSQL. No se conoce todavía la huella del clúster desde mantenimiento.

## Corrección
- La variable `PORT` inyectada por Railway ya no se clasifica automáticamente como evidencia de exposición pública. Si está definida, se exige entero decimal ASCII en intervalo 1..65535; otros valores generan `INVALID_RUNTIME_PORT`.
- `RAILWAY_PUBLIC_DOMAIN`, `RAILWAY_STATIC_URL` y `APP_BASE_URL` se mantienen bloqueados sin excepción.
- Permanecen inalterados los pins exactos de proyecto, entorno, ID de mantenimiento, private domain y destino PostgreSQL; credenciales externas prohibidas, todos los `SELECT` catalogales en transacción READ ONLY, rollback, comprobación de PostgreSQL 18 y del system_identifier `7696213098351943739`.
- El ejecutor administrativo **no es un servidor web**, no hace bind ni escucha en `PORT`, no importa `app.py` ni admite DDL.
- Las comprobaciones de variables de entorno no reemplazan el inventario Railway: verificar independientemente que no hay dominio público, custom domain, TCP proxy, cron ni política de reinicio; confirmar que el SHA de ejecución es inmutable.

## Condición de salida
Este cambio es **solo código de una rama nueva y CI sintética**, sobre la PR #70. Ninguna modificación de Railway, PostgreSQL lab, staging, producción o `main` queda autorizada por el mero merge de código ni por CI verde.

Si se desea una tercera ejecución de **solo lectura**, hacer preflight operativo independiente, pin exacto del SHA validado y **una única ejecución**, con reinicio NEVER; ante cualquier denegación, parar. No crear tablas, no restaurar backup original, no pagar, no enviar correo, no fusionar PRs y no desplegar web.

**NO-GO para migraciones y operaciones destructivas.**


## Resultado ejecutado de la tercera comprobación real
- Commit CI validado y anclado al ejecutor: `2062109d900281f383bc1f3a5c94a98be7140d62`. CI **34/34 PASS**, run `38541234720`.
- Despliegue privado de solo lectura: `86336018-9964-471b-92c7-e4b40db8e4e1`.
- Línea de registro literal: `S01 STG-B10G: PASS (READ ONLY, PostgreSQL18, cluster 7696213098351943739, pristine schema)`.
- El `system_identifier` coincide **exactamente** con la lectura aportada por el propietario desde `Postgres > Database > Query` (`7696213098351943739`), con base `railway` y PostgreSQL 18; el esquema estaba vacío según la inspección de catálogos del preflight.
- Sin migraciones, DML, DDL, envíos, cobros ni activación de web: el script incluye solo consultas a catálogos y control, en transacciones READ ONLY con rollback.
- `sslmode=require` cifra la conexión, pero NO sustituye verificación del certificado servidor `verify-full`. La coincidencia de huella, pins Railway y referencia interna constituye evidencia operacional del clúster, no prueba absoluta de seguridad de red.
- Tras la comprobación la ejecución de mantenimiento no tiene ninguna razón para permanecer activa; conservar política `restartPolicyType=NEVER`, sin cron ni endpoints públicos.
- **PENDIENTE:** copia de seguridad del laboratorio restaurada y verificada en destino separado. La comprobación de identidad, por sí sola, **no autoriza** bootstrap o migraciones reales.
