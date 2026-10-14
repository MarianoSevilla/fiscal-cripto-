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
