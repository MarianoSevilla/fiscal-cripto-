# S01 · STG-B05 — Servicio web vacío creado en laboratorio independiente

**Fecha:** 13/10/2026. **Autorización:** «procede» del propietario tras la propuesta explícita de crear exclusivamente un servicio web vacío, sin conectar GitHub ni desplegar código.

## Resultado de Railway, verificado en lectura posterior a la creación

| Recurso | Valor / estado |
|---|---|
| Proyecto privado | `fiscal-cripto-s01-lab`, ID `5f26aa6e-2e6d-46ef-bb5f-bca4ece07d5e` |
| Entorno | `lab`, ID `3f9758ef-4e26-4e8d-9dd4-7b9286d81ea8` |
| **Nuevo servicio web vacío** | **`s01-lab-web`**, ID **`212f4f52-b349-4387-a046-9f6b08237d2e`** |
| Repositorio / imagen | **Ninguno** (source `null`) |
| Despliegues web | **0**: `latestDeployment = null`, lista de deployments vacía |
| Variables de servicio web | **0** |
| Dominios Railway públicos / dominios personalizados | **0 / 0** |
| Proxies TCP públicos | **0** |
| Volumen web | Ninguno |
| PostgreSQL laboratorio | `Postgres` ID `f680f3fc-4581-44ff-8bc1-d034840f2c7e`; online, deployment anterior SUCCESS |
| Volumen PostgreSQL | `postgres-volume` ID `c35d178f-7473-4d0b-adb9-1faae815b7af`; preservado |
| Cambios staged en `lab` | **0** |
| Datos PostgreSQL (última verificación propietario antes de B05) | PostgreSQL 18.6, `public` **0 tablas**; **no se volvió a ejecutar SQL en B05** |

`create_service` se invocó con `projectId`, `environmentId` y `name` exactos; **sin** `image`, fuente GitHub, variables, permisos, volumen o dominios. El inventario posterior confirmó exclusivamente **dos servicios (Postgres + servicio web vacío)** y **un volumen PostgreSQL**.

## Protección del software

- La PR **#62** sigue en borrador en la rama `security/s01-stg-b04-railway-lab-lock`, cabeza **`66084c224880e369d6b9432da371c7e9f620ae19`**, basada en PR #61. GitHub Required CI #38445269777: **SUCCESS** (1.886 Python pass, 63 skip; PG18 y Chromium pass).
- **S01-LAB-LOCK no se ha modificado** para insertar el ID nuevo. La constante de `web_service_id` en `lab_isolation.py` sigue deliberadamente **None**: arranque real del laboratorio **NO-GO** hasta una nueva revisión/PR y autorización.
- GitHub `main` y Railway production siguen en `56882073295faae3bd1bc3632288a970acb330da`; el staging existente conserva el despliegue `f421a9c21f99267eb0aedf05705c93b62fba3ba9`. Ninguno fue modificado por B05.

## Gates pendientes — no autorizados por la creación

1. Confirmar la política futura de origen: no hay todavía dominio web público. Evaluar URL interna/canal privado o un acceso protegido antes de fijar `APP_BASE_URL`; no inventar un origin HTTPS.
2. Comprobar la referencia real del nuevo PostgreSQL desde el futuro servicio web (la validación requiere una DSN exacta del Postgres de **lab**, nunca de staging/prod). La aplicación todavía no tiene ninguna variable configurada.
3. Obtener autorización para **modificar código** de `lab_isolation.py` y actualizar pruebas/CI con el nuevo web ID y el origen verificado, sin merges.
4. Autorizar aparte variables de laboratorio, permisos de DB, bootstrap/migraciones y despliegue de GitHub desde SHA exacto.
5. Mantener PayPal, Stripe, Resend, Google OAuth y webhooks sin claves. No ejecutar pruebas financieras reales. Ninguna alteración de producción/staging.

**Estado: B05 creación vacía COMPLETADA. Base de datos vacía y web sin ejecutar; todavía NO-GO para despliegue/DDL.**
