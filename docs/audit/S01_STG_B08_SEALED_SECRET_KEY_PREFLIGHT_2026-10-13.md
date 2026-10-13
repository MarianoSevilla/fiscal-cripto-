# S01 · STG-B08 — Preparación de SECRET_KEY y comprobación previa de cambios

**Fecha:** 2026-10-13. **Estado: preparado para intervención del propietario; clave aún NO añadida / NO sellada.**
Autorización del propietario: «sí» para **preparar clave segura y verificar configuración**, sin despliegues. Esta fase **no autoriza** aceptar cambios staged, desplegar, asociar GitHub, SQL/DDL, migrar ni alterar producción/staging.

## 1. Evidencia de solo lectura (comprobada antes de esta nota)

- Proyecto independiente `fiscal-cripto-s01-lab` (`5f26aa6e-2e6d-46ef-bb5f-bca4ece07d5e`), entorno `lab` (`3f9758ef-4e26-4e8d-9dd4-7b9286d81ea8`).
- Servicio web **único con cambios** `s01-lab-web` (`212f4f52-b349-4387-a046-9f6b08237d2e`). Sin código conectado, sin variables propias activadas, sin deployments, sin dominio público ni proxy TCP.
- PostgreSQL propio `Postgres` (`f680f3fc-4581-44ff-8bc1-d034840f2c7e`): ONLINE y sin cambios pendientes. Última consulta SQL del propietario: PostgreSQL 18.6, base `railway`, `public` con cero tablas. Esta fase no realiza SQL ni escrituras.
- **Patch pendiente** `7e481ca6-0d26-40e1-83cc-76f08b963f03`: **STAGED**, 14 cambios no destructivos exactamente, todos sobre `s01-lab-web`, sin variables compartidas ni modificaciones de volúmenes/Postgres.
- 11 variables previstas: `ADMIN_EMAILS`, `APP_BASE_URL`, `DATABASE_URL`, `ENABLE_ADVISORY_STATUS_EMAILS`, `ENABLE_ADVISORY_UPLOADS`, `FISCAL_ADVISOR_EMAILS`, `FLASK_ENV`, `PAYPAL_ENVIRONMENT`, `PORT`, `PROCESSING_ERROR_EMAILS_ENABLED`, `RESEND_FROM_EMAIL`. Tres ajustes: dominio privado `s01-lab-web`, `/healthz`, restart `NEVER`.
- **`SECRET_KEY` ausente** de variables activas y de cambios staged; **0 sealed vars en web** al momento de comprobación. No se ha creado ni leído ninguna clave.
- La PR #63 permanece DRAFT, cabeza `9f8060ce2e096165b33dbae25276c91d52f4ed15` con CI PASS (1904 Python PASS, 63 skipped; PostgreSQL 18/Chromium PASS), sin merge.

## 2. Motivo por el que NO se introduce la clave mediante la integración

Railway admite **Sealed variables** que, una vez selladas, proporcionan su valor a builds/runtimes sin mostrarlo en UI/API. El conector Railway disponible permite `set_variables` (y `staged=true`), **pero no ofrece la acción Seal**. Introducir el secreto por el conector dejaría un paso temporal sin sellar y expondría el valor en la llamada de herramienta. No es aceptable en el protocolo de seguridad.

Las funciones `secret(length)` que Railway documenta son **funciones de plantillas cuando se despliegan plantillas**, no está demostrado que puedan añadirse como variable secreta ordinaria del web. **No usarlas como sustituto** de una clave generada en entorno del propietario.

## 3. Única intervención pendiente del propietario

**La clave debe generarse localmente en el Mac y pegarse exclusivamente en Railway, sin compartirla en ChatGPT ni en GitHub.** Comando independiente de la aplicación:

```sh
python3 -c 'import secrets; print(secrets.token_urlsafe(48))'
```

Se obtienen 48 bytes aleatorios criptográficamente seguros, codificados en una cadena URL-safe de ~64 caracteres. No usar/guardar valor real en repositorio, correo, logs, capturas ni mensajes. Cerrar terminal cuando ya esté cargada/asegurada y borrar portapapeles si se ha copiado. No reutilizar la clave productiva o de staging.

Ruta: [Proyecto Railway del laboratorio](https://railway.com/project/5f26aa6e-2e6d-46ef-bb5f-bca4ece07d5e) → entorno `lab` → servicio `s01-lab-web` → **Variables** → añadir `SECRET_KEY` con el valor recién generado → guardar como cambio pendiente (**no Apply / Deploy**). Menú de tres puntos de `SECRET_KEY` → **Seal**. Si Railway no permite sellar la variable mientras se encuentra staged, **DETENERSE, no aplicar el patch para poder sellarla**. Registrar únicamente que el sellado es posible/efectuado, NUNCA el valor.

Referencia oficial: [Railway Using Variables — Sealed variables](https://docs.railway.com/variables#sealed-variables), que indica la opción `…` → `Seal`, no revela después el valor y no permite desellar la variable.

## 4. Validación de solo lectura tras la intervención

Revisar mediante `list_variables` y `get_staged_changes` que:

1. El servicio exacto `212f4f52-b349-4387-a046-9f6b08237d2e` contiene `SECRET_KEY` **sellada**. Si el conector no refleja sellado de un cambio todavía staged, confirmar visualmente el estado de `Seal` desde Railway sin mostrar el valor. No inventar evidencia de sellado.
2. No hay credenciales Stripe, PayPal, Resend, Google, Turnstile u otras; no hay variables de roles reales ni flags que habiliten envíos/pagos/uploads.
3. El patch sigue **STAGED y no destructivo**, pasa de 14 a **15 cambios esperados** (11 variables anteriores + `SECRET_KEY` + 3 ajustes), y afecta exclusivamente al servicio web. Un cambio del patch ID se verifica y documenta: no asumir que siga siendo el mismo si Railway crea otra revisión.
4. DB sigue separada y sin cambios, web sigue sin source ni deployments, 0 dominios o TCP públicos; originales production/staging conservan deploys y no tienen staged changes.
5. **NO llamar a `accept-deploy`** ni crear/adjuntar fuente; configurar SECRET_KEY no autoriza migrar o iniciar web.

## 5. Gate siguiente

Solo con evidencia del secreto preparado y guardas verificados, solicitar autorización **nueva e independiente** para aplicar cambios al web. Aun con web configurada y `SECRET_KEY`, **Postgres lab no tiene las tablas requeridas**; la inicialización es otro gate y necesita permiso separado. **Nada de pagos reales ni proveedores**.

**Estado al documentar:** B08 revisión READ-ONLY completada; acción Seal del propietario pendiente. Infraestructura sin despliegues adicionales.
