# STG-B11F — Verificación PostgreSQL18 de la sonda B11B y expediente del bloqueo de conexión

**Fecha:** 14/10/2026. **Ámbito autorizado:** lecturas del estado Railway/GitHub, documentación oficial y CI con PostgreSQL desechable. **NO se repite la conexión del repositorio bloqueada**, no se modifica la configuración de Railway, no se ejecuta DDL real.

## 1. Estado verificado antes de intervenir

- Proyecto Railway aislado `fiscal-cripto-s01-lab`, ID `5f26aa6e-2e6d-46ef-bb5f-bca4ece07d5e`, entorno `lab` ID `3f9758ef-4e26-4e8d-9dd4-7b9286d81ea8`. Cuenta Railway autenticada, registrada y con acceso de lectura al proyecto.
- Base original: servicio `Postgres`, ID `f680f3fc-4581-44ff-8bc1-d034840f2c7e`, clúster `7696213098351943739`, volumen `c35d178f-7473-4d0b-adb9-1faae815b7af` — sin escrituras.
- Destino propuesto: `Postgres-Im3h`, ID `317b21e9-b259-4b15-902a-a7bec69b7407`, clúster `7696517018472497211`, volumen independiente `16144c31-17d5-49e7-a725-967e883e03f9`; copia vacía restaurada en B10S, pero no se ha inicializado el esquema S01.
- Servicio administrador B11B: `s01-lab-schema-preflight`, ID `007db029-c99d-4a68-a965-fd0de3496614`, sin repositorio conectado, sin deployment, sin dominio público/proxy/volumen, restart `NEVER`; configurado para `Dockerfile` en `/infra/s01_lab_schema`, inicio `python3 /app/preflight.py`. Única variable añadida: referencia privada `TARGET_DATABASE_URL=${{Postgres-Im3h.DATABASE_URL}}`.
- Servicio de mantenimiento antiguo `s01-lab-maintenance` apunta al Postgres original, NO debe utilizarse como escritor o sustituto de B11B.
- PR #87 B11E draft, CI [#38622991813](https://github.com/MarianoSevilla/fiscal-cripto-/actions/runs/38622991813) **SUCCESS 29/29**, puerta `bootstrap_release_gate.py` permanentemente NO-GO y Dockerfile actual exclusivo de lectura.
- `main` sigue en `56882073295faae3bd1bc3632288a970acb330da`. Entorno Railway sin cambios pendientes.

## 2. Naturaleza del bloqueo B11B

El anterior intento de `connect_service_source` para la sonda B11B fue **rechazado por un control de seguridad de la plataforma**. El registro disponible en la conversación solo deja acreditado ese rechazo, no un código técnico detallado del bloqueo. **No puede afirmarse que se debiera a la GitHub App, permisos, un token caducado o un error de Railway**.

La consulta de documentación oficial aporta únicamente contexto, no diagnostica el rechazo concreto:
- [Railway — Service source / GitHub](https://docs.railway.com/services#deploying-from-a-github-repo): para seleccionar un repositorio en Railway hay que vincular la cuenta y autorizar la aplicación Railway GitHub; los despliegues pueden requerir aprobación del miembro autorizado.
- [Railway — Connect a service to a repo](https://docs.railway.com/integrations/api/manage-services#connect-a-service-to-a-repo): operación de vinculación de fuente al servicio; explica el mecanismo habitual, **no** el motivo del rechazo del conector.

**NO usar** terminal Railway, `railway up`, GitHub Actions de despliegue, nuevo servicio de reemplazo, Docker registry o la interfaz web para evadir un control de seguridad aún activo. Revisar datos/permisos por canales oficiales es admisible; volver a ejecutar un despliegue solo después de confirmación de que el bloqueo está resuelto y una autorización técnica nueva.

### Solicitud de diagnóstico al proveedor / equipo autorizado

> Proyecto Railway S01 `5f26aa6e-2e6d-46ef-bb5f-bca4ece07d5e`, environment `lab` `3f9758ef-4e26-4e8d-9dd4-7b9286d81ea8`, service `s01-lab-schema-preflight` (`007db029-c99d-4a68-a965-fd0de3496614`). La conexión controlada de un servicio privado sin dominios ni volúmenes al repositorio `MarianoSevilla/fiscal-cripto-` para una sonda read-only fue rechazada por un control de seguridad de la plataforma. ¿Podéis identificar el control y su causa concreta, comprobar autorización del repositorio y facilitar el procedimiento legítimo para habilitar **únicamente** esta sonda de lectura? No se solicita aprobar un despliegue de migraciones ni acceso a bases de producción. No se volverá a conectar ni desplegar mientras no quede resuelto el bloqueo.

**La petición debe enviarse a través de un canal autorizado** por el propietario; esta PR no envía comunicaciones externas.

## 3. Ensayo suplementario B11F — consulta real, CI solamente

Los tests B11B/B11E anteriores estaban centrados en validaciones estáticas, usando un subprocess simulado. El ensayo B11F utiliza la **cadena SQL sin cambios de `preflight.SQL` de B11B** contra un PostgreSQL18 real pero disposable de GitHub Actions, con `POSTGRES_DB=railway`, host local `127.0.0.1:5432` y contraseña fija que no pertenece a Railway:

1. Exige `CI=true`, `GITHUB_ACTIONS=true`, `RUNNER_OS=Linux`, y ausencia de variables `RAILWAY_*`, `DATABASE_URL`, `TARGET_DATABASE_URL`, aprobación de esquema o conexión externa.
2. Lee `server_version_num` y `pg_control_system().system_identifier` de **ese contenedor**. Rechaza la huella de cualquiera de los dos clústeres S01 reales. Pin temporal de prueba para la versión/huella sintéticas; la implementación productiva mantiene el pin real `180006` / `7696517018472497211`.
3. La sonda `preflight.preflight` exige primero una identidad sintética idéntica en formato a B11B; el *runner de pruebas* comprueba el comando SQL EXACTO y los flags read-only/TLS y redirige después la consulta exclusivamente al servidor PG18 Docker local. El propio script CI **no se copia al Dockerfile B11B** y no puede habilitar tráfico Railway.
4. Caso positivo: BD `railway` fresca, 6 categorías de objetos esperadas en cero; `PASS`.
5. Caso negativo: el *propio test CI* crea una tabla y una fila sintética, ejecuta la misma consulta de lectura y exige `SCHEMA_NOT_PRISTINE`. Comprueba que la fila permanece intacta tras el rechazo.
6. Contratos offline adicionales prueban entorno no CI, identidades inválidas, SQL no permitido, PGOPTIONS readonly ausente y que el contenedor de solo lectura no contiene código de prueba ni motor de migración.

**Limitación:** redirigir el transporte a Docker CI prueba el SQL/parser real de B11B, no prueba la identidad de red efectiva del servicio Railway B11B. Esta última sigue pendiente y bloqueada.

## 4. Gates no cubiertos aún

- Bloqueo de vinculación B11B: **pendiente de diagnóstico formal**, sin reintento.
- Conexión efectiva B11B → `Postgres-Im3h`: **no probada en vivo**.
- Primera DDL real `db.create_all`, `stamp`, Alembic `upgrade`: **NO-GO** hasta revisión de ejecutor final, aceptación de riesgos de esquema parcial y autorización específica del propietario.
- Estado principal: no fusionar PR, no modificar `main`, no instalar dependencias en Railway, no acceso público, no pagos, correos, web, ni escritura a PostgreSQL de origen o recuperado.
