# S01 · STG-B03 — PostgreSQL del laboratorio activado (sin web ni migraciones)

**Fecha 13/10/2026. Autorización expresa del propietario: «sí» para aplicar exclusivamente PostgreSQL 18 + volumen del laboratorio**. Este documento registra la operación, no extiende sus permisos.

## Objetivo y operación ejecutada

- Proyecto **privado** `fiscal-cripto-s01-lab` ID `5f26aa6e-2e6d-46ef-bb5f-bca4ece07d5e`; entorno independiente `lab` ID `3f9758ef-4e26-4e8d-9dd4-7b9286d81ea8`.
- Preflight: patch `afe9f2ee-d27b-46d1-b8ca-f62024a4c809` **STAGED**, no destructivo, 2 recursos exactamente: creación de servicio PostgreSQL y de volumen; sin dominios públicos, TCP proxies, grupos o cambios a variables compartidas.
- Operación: `accept-deploy` exclusivamente sobre el **environment ID lab**, con confirmación de Railway `committed=true`, workflow `commitChanges/3f9758ef-4e26-4e8d-9dd4-7b9286d81ea8/afe9f2ee-d27b-46d1-b8ca-f62024a4c809`.
- Servicio `Postgres` ID `f680f3fc-4581-44ff-8bc1-d034840f2c7e`, imagen `ghcr.io/railwayapp-templates/postgres-ssl:18`; deployment `cf076b94-1f68-4d31-b143-3277d40ef188`: **SUCCESS, online, 1/1 réplica, 0 advertencias y 0 críticos** al verificar.
- Volumen `postgres-volume` ID `c35d178f-7473-4d0b-adb9-1faae815b7af`, estado **live**, montado solo en dicho Postgres en `/var/lib/postgresql/data`.
- Inventario del laboratorio después: **un solo servicio**, un volumen y **cero cambios staged**; sin dominios ni TCP proxies públicos. No se ha creado ni desplegado aplicación web, no existe `S01-LAB-LOCK` desplegada, no se han copiado datos ni contraseñas de otros entornos.
- No se ha conectado por SQL ni realizado DDL, Alembic, `bootstrap_db.py`, migraciones, pagos o envíos de email. PostgreSQL online **no acredita aún la versión de `alembic_version` ni un esquema inicial vacío**; eso se comprobará después con solo lecturas, sin asumir tablas.

## Verificación cruzada sin mutación de entornos anteriores

| Elemento | SHA / estado comprobado |
|---|---|
| GitHub `main` | `56882073295faae3bd1bc3632288a970acb330da` |
| Railway producción web | Deployment SUCCESS en `56882073295faae3bd1bc3632288a970acb330da`; cero staged |
| Railway staging web | Deployment SUCCESS en `f421a9c21f99267eb0aedf05705c93b62fba3ba9`; cero staged |
| PR #61 | `e4b8fdec505f0893ec7f61bc89d7febc28e6d6a3`, DRAFT sin fusionar |

## Próximo gate independiente, no autorizado todavía

1. Revisión **solo lectura** de variables no sensibles, versión PostgreSQL, inventario tablas de `lab`, redes; no imprimir secretos ni DSN completo. Si hay tablas no esperadas, STOP.
2. Desarrollo y CI de nueva barrera `S01-LAB-LOCK` con la identidad real de `lab`, separada de `STG-LOCK-001`, que siga preservando los bloqueos financieros.
3. Solicitar permiso específico para ejecutar `bootstrap_db.py` **únicamente** sobre lab cuando se haya auditado el destino, procedimiento de restauración y aislamiento.
4. Solicitar permiso distinto para crear/desplegar web y probar recuperación.

**Coste**: PostgreSQL ya está ejecutándose y puede consumir CPU/memoria/almacenamiento de forma facturable. No se ha programado ni ejecutado una parada automática; cualquier parada o eliminación requiere una orden específica. La ausencia de un límite de coste global evita intervenir accidentalmente en producción. Debe acordarse duración de la prueba.

Documentos de referencia: `S01_STG_B03_INDEPENDENT_RAILWAY_LAB_DESIGN_2026-10-13.md`, `S01_STG_B03_PROJECT_CREATED_POSTGRES_STAGED_2026-10-13.md`.
