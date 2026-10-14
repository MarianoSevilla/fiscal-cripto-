# S01 — Ensayo de restauración local desde copia de producción

**Preparación: 13/10/2026. DRAFT · NO MERGE · NO DEPLOY · NO COBROS.**

Base: PR #44, commit 832220ad6b3804fa83838b0b6be2ec34b0971855. No acceder a Railway, Stripe, PayPal, MERU ni a producción. No enviar copias de seguridad ni datos a GitHub Actions o ChatGPT.

## Motivo del ensayo

La prueba anterior de PG18 solo reproducía las tres migraciones S01 sobre una tabla histórica mínima. La comprobación restante debe ejecutar el proceso real bootstrap_db.py, que importa app.py y puede llamar a db.create_all(), sobre una restauración integral de la base. Este procedimiento se ejecuta únicamente en el equipo local del propietario.

## Requisitos

- PostgreSQL 18 Homebrew en el Mac mini, con initdb, pg_ctl, psql y pg_restore.
- Intérprete Python con las dependencias de la app instaladas. No ejecutar como root.
- Copia local de producción anterior a S01, formato custom de pg_dump, con permisos 0600 y sin symlinks.
- SHA-256 **previamente registrado** en un archivo lateral local de una sola línea con formato shasum -a 256. Un checksum generado por primera vez durante el ensayo no demostraría procedencia previa.
- **No** subir la copia .dump, logs, hash, credenciales ni datos del cliente a GitHub, CI o el chat.

## Comandos de uso local

En un checkout de la rama de esta PR, desde su raíz, y con el Python del proyecto activado:

    BACKUP="$HOME/railway-backups/fiscal-cripto-production-20261010-234816.dump"
    SHA_FILE="$BACKUP.sha256"
    PG_BIN="$(brew --prefix postgresql@18)/bin"

    python fiscal_app_export/tools/s01_rehearse_restored_backup.py \
      --backup "$BACKUP" --sha-file "$SHA_FILE" \
      --pg-bin "$PG_BIN" --preflight-only

    # Exclusivamente después de superar el preflight:
    python fiscal_app_export/tools/s01_rehearse_restored_backup.py \
      --backup "$BACKUP" --sha-file "$SHA_FILE" --pg-bin "$PG_BIN"

Si el checksum original tiene otro nombre, usar su ruta verdadera. Si no existe o no se dispone de hash fiable guardado con anterioridad, detener el ensayo y no improvisar otro.

## Invariantes y validaciones

1. Archivo de respaldo regular, del usuario, permiso privado 0600, custom PGDMP y digest SHA-256 coincidente. Inspección de formato con pg_restore --list sin imprimir el índice.
2. Servidor PostgreSQL 18 nuevo en directorio temporal privado (0700), solo socket Unix, escuchas TCP deshabilitadas y base ficticia s01_local_rehearsal. Todas las herramientas reciben variables PGHOST/PGPORT/PGUSER construidas localmente; no heredan DATABASE_URL o credenciales de producción.
3. Restauración completa con pg_restore --exit-on-error --single-transaction, revisión Alembic inicial v5w6x7y8z9a0.
4. Recuento y huella de las columnas históricas de todas las tablas originales. No se exportan ni imprimen datos ni huellas.
5. Ejecución del **bootstrap_db.py real**, dos veces consecutivas para comprobar idempotencia. Se inyectan claves sintéticas y guardia Python contra sockets IP y DNS; ninguna llamada a Stripe, Resend o PayPal.
6. Revisión final z9a0b1c2d3e4; las tres tablas S01 quedan vacías, con constraints e índices obligatorios, sin tablas añadidas inesperadamente; el desglose histórico de honorarios y comisiones queda NULL y cada registro histórico (incluidas referencias PayPal) conserva su huella.
7. Se detiene PG temporal con pg_ctl y se destruye únicamente el directorio temporal creado por el script, nunca la copia original. Si fallase la detención, los archivos privados se conservan para revisión manual y se advierte la ruta local.

## Límites y dictamen

El SHA-256 no certifica por sí solo la autenticidad del origen del backup. Las huellas md5 detectan alteraciones accidentales, no sustituyen una firma robusta frente a ataques maliciosos. Bloquear sockets IP de Python no constituye aislamiento de red a nivel de sistema; PostgreSQL está configurado sin TCP. SIGKILL o apagado inesperado puede dejar un directorio de datos local privado sin limpiar.

Este control no concilia PayPal contra registros del proveedor, no realiza pagos Stripe ni integra endpoints de producción, notificaciones reales, reembolsos, disputas, MERU ni facturación. La facturación la lleva Rafa.

La CI de esta PR puede probar **solo las barreras con archivos inventados**; no puede acceder a la copia real del Mac. El control de restauración continuará PENDIENTE / NO-GO hasta que el propietario ejecute preflight y ensayo local y reporte únicamente PASS/FAIL, sin contenido ni datos personales.

## Ensayo real local — primer intento (13/10/2026): NO-GO

El propietario ejecutó el preflight y la restauración del respaldo original con SHA-256 válido. La copia PostgreSQL 18 se restauró con revisión inicial correcta. La primera invocación real de `bootstrap_db.py` falló con `TypeError` antes de Alembic. Una extracción de traceback sin datos sensibles situó el problema en `sqlalchemy/util/concurrency.py:13` (importación de `asyncio`).

**Causa reproducida sin datos reales:** el `sitecustomize.py` del runner sustituía `socket.socket` por una función para bloquear conexiones IP; durante la importación de `ssl`, Python 3.13 hereda de `socket.socket` y requiere que sea una clase. Esto falla con `TypeError`. La corrección de esta PR conserva una subclase de socket, mantiene el rechazo de AF_INET/AF_INET6 y DNS y permite sockets AF_UNIX. Añadidas pruebas de subprocess Python aislado para `asyncio`, `ssl` y SQLAlchemy bajo el guard.

**No ejecutar cobros, migraciones en producción ni realizar una tercera restauración local hasta que la CI de este fix sea satisfactoria.** El NO-GO histórico no debe editarse retrospectivamente: será necesario volver a ejecutar el ensayo entero y obtener PASS en el Mac. El primer intento no demuestra una deficiencia del esquema ni que las migraciones estén aprobadas.
