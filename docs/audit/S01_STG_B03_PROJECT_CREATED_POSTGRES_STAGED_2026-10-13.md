# S01 STG-B03 · Alta aislada y PostgreSQL 18 preparado (sin activar)

**13/10/2026 · CONTROL DE CAMBIOS · SOLO PROYECTO CREADO, BD STAGED.**

## Autorización y alcance

Propietario: «pk, procede» tras el plan de STG-B03, limitado a proyecto Railway nuevo + PostgreSQL 18 privado, sin aplicación web, copias de datos, credenciales de otros entornos, DDL, migraciones ni despliegue S01.

La comprobación previa de costes mostró tarifas públicas Railway de referencia: RAM 10 USD/GB-mes; CPU 20 USD/vCPU-mes; volumen 0,15 USD/GB-mes; egress 0,05 USD/GB. El gasto final depende del consumo, plazo y plan del workspace. **No se ha podido leer el plan concreto ni confirmar un límite de gasto del usuario; por ello no se ha activado PostgreSQL ni el volumen.** Este estado evita costes de cómputo continuos atribuibles a los nuevos servicios staged. No establecer un hard limit del workspace existente sin autorización, porque podría detener producción.

## Estado real de recursos Railway verificado

| Recurso | ID o referencia | Estado |
|---|---|---|
| Workspace existente | `fd067863-d63d-4009-80eb-aec248399632` | No alterado |
| Proyecto nuevo y PRIVADO | `fiscal-cripto-s01-lab` — `5f26aa6e-2e6d-46ef-bb5f-bca4ece07d5e` | **CREADO**, PR deploys desactivados |
| Entorno nuevo | `lab` — `3f9758ef-4e26-4e8d-9dd4-7b9286d81ea8` | Creado |
| Servicio Postgres | `f680f3fc-4581-44ff-8bc1-d034840f2c7e` | **STAGED-CREATE**; no runtime |
| Imagen propuesta | `ghcr.io/railwayapp-templates/postgres-ssl:18` | Imagen exacta de plantilla oficial Railway `postgres` |
| Volumen PostgreSQL | `c35d178f-7473-4d0b-adb9-1faae815b7af` | **STAGED-CREATE**, montaje `/var/lib/postgresql/data` |
| Patch Railway sin aplicar | `afe9f2ee-d27b-46d1-b8ca-f62024a4c809` | STAGED, 39 cambios (2 recursos), **no aplicado** |

El inventario confirma **cero deployments** para `lab`, **cero servicios vivos**, **sin dominios públicos ni proxies TCP** en la configuración preparada. La plantilla declaraba una sola instancia PostgreSQL 18 (no HA), un volumen y secretos autogenerados por Railway; no se ha leído, copiado ni entregado contraseña.

**NOTA CRÍTICA:** el servicio PostgreSQL y el volumen todavía **no están provisionados**. En particular, no existe una nueva BD a la que conectarse, por lo que no hay schema Alembic ni consultas SQL ejecutadas. *Staged* NO significa *online*.

## Controles que faltan antes de aplicar el patch

1. Confirmar plan y crédito disponible del workspace; revisar tarifas y posibles costes estimados del volumen y servicio en un periodo limitado. Obtener aprobación de gasto máximo o duración operativa. No asumir que un nuevo proyecto tiene cuota independiente.
2. Confirmar en Railway el patch exacto: exclusivamente Postgres + volumen nuevo sin TCP proxy/dominio, nada que enlace DB a producción/staging, referencia de servicio privada, contraseña generada internamente. Si surgen cambios inesperados, STOP y revisión.
3. Acordar fecha de apagado/limpieza de servicios del lab para evitar cargo por funcionamiento indefinido. **No tocar ni cerrar producción**.
4. Solicitar una nueva autorización para **aplicar** el patch en el entorno `lab`. La acción `accept-deploy` provisionará PostgreSQL y puede generar gastos; **no se ha ejecutado**.
5. Tras aprobación y activación de solo PostgreSQL, inspeccionar identidad/host/DB y cantidad de tablas (debe ser 0 antes de bootstrap). Autorizar por separado la implementación `S01-LAB-LOCK`, web, migraciones, tests y recuperación.

## Protección del resto de la aplicación

Al concluir, `main` seguía en `56882073295faae3bd1bc3632288a970acb330da`; el candidato PR #61 en `e4b8fdec505f0893ec7f61bc89d7febc28e6d6a3`. **Ninguna rama, PR o configuración Railway original fue fusionada ni publicada**. El ensayo de BD sigue sin empezar.

Referencias: [Diseño STG-B03](S01_STG_B03_INDEPENDENT_RAILWAY_LAB_DESIGN_2026-10-13.md), [Railway Pricing](https://railway.com/pricing), [Railway cost control](https://docs.railway.com/pricing/cost-control), [Controlling GitHub Autodeploys](https://docs.railway.com/deployments/github-autodeploys).
