# SEC5-CSRF-001 — Auditoría inicial de rutas mutables (28/10/2026)

**Estado: hallazgos estáticos, no vulnerabilidad explotada demostrada.** Alcance: lectura de `fiscal_app_export/app.py` y `security_config.py` en `main`. Sin peticiones a producción ni cambios ejecutables.

## Protecciones verificadas
- `SESSION_COOKIE_SAMESITE=Lax`, `Secure` y `HttpOnly` en producción; `REMEMBER_COOKIE_SAMESITE=Lax`.
- `auth_request_boundary` (app.py, ~809) restringe los POST de `AUTH_POST_PATHS` mediante Origin presente o `Sec-Fetch-Site=cross-site`. No es middleware general para todos los verbos/rutas.
- Gestión interna C1 de asesoramiento (app.py, ~5508): `_c1_csrf_ok` exige token ligado a usuario/sesión y verifica Origin si se proporciona.
- CORS permite tres orígenes propios y credenciales; **CORS no sustituye verificación CSRF**. SameSite=Lax reduce escenarios de envío de cookies cross-site, no garantiza cubrir todos los modelos de amenaza.

## Rutas que requieren pruebas adversariales (no inferir explotación)

| Grupo | Ejemplos visibles en app.py | Análisis pendiente |
|---|---|---|
| Recursos admin | `POST /api/admin/recursos/solicitudes/<id>/estado`, `/nota`; `DELETE /api/admin/recursos/solicitudes/<id>` | Funciones sin comprobación CSRF explícita; reproducir desde cliente autenticado con Origin externo, sin Origin, y tipos MIME distintos |
| Contactos admin | `PATCH /api/admin/contactos/<id>` | Cobertura de PATCH y petición simple/preflight; no modificar registros reales |
| Asesoramiento heredado | `POST /api/admin/asesoramiento/solicitudes/<id>/estado`, `/nota`, `/is-test`; `DELETE /api/admin/asesoramiento/solicitudes/<id>` | Antes comprobar `advisory_financial_prefreeze`: rutas podrían quedar bloqueadas por PREFREEZE, lo que cambia severidad |
| C1 protegidas | `POST .../gestion/nota` y `.../gestion/estado` | Control positivo de token y negativos con sesión distinta, Origin inválido o ausente |
| Perfil y cuenta | `POST /api/change-password`, `/api/update-profile`, `/api/delete-account` | Confirmar cobertura de `AUTH_POST_PATHS` y barreras de credenciales/OAuth |
| Peticiones públicas y subida | `POST /api/recursos/solicitar`, `/api/asesoramiento/solicitar`, `/api/diagnostico-archivo` | Separar CSRF de spam, consentimiento, origen explícito, sesión y límites; el diagnóstico comprueba Origin en su propia ruta |
| Pagos y webhooks | `POST /api/pago/iniciar/<token>`, `/api/webhooks/stripe` | Analizar firmas de proveedor y tokens de capacidad; no aplicar token CSRF de sesión indiscriminadamente a webhooks |

## Batería mínima de pruebas en Flask test client + navegador

- Para cada ruta mutable sensible: `Origin` externo, `Origin` ausente, `Sec-Fetch-Site: cross-site`, `Content-Type` JSON vs `text/plain` vs formulario y método POST/PATCH/DELETE.
- Confirmar que un 403/400 ocurre **antes de cualquier commit, email o llamada externa**; comprobar estado en SQLite/PostgreSQL sintéticos.
- Control positivo: operaciones legítimas desde dominio canónico siguen funcionando; cubrir el paso WWW → apex y peticiones `fetch` reales.
- Variantes: usuario anónimo, usuario estándar, administrador, asesor, tokens CSRF correctos/incorrectos, cookies SameSite y cabeceras omitidas.
- Pruebas específicas de Origin/Subdominio: origen cruzado entre subdominios de marianosevilla.com; el atributo SameSite considera el sitio, no el origen.
- No reutilizar credenciales reales ni ejecutar solicitudes mutables en producción.

## Criterio de corrección proporcional
Primero reproducir impacto. Si una ruta sensible realmente permite un cambio no autorizado bajo el modelo de amenaza, añadir protección compartida limitada a rutas relevantes, con verificación robusta de origen y/o token CSRF para sesiones; nunca bloquear webhooks verificados ni flujos válidos de pago. No concluir explotación por mera ausencia de decorador.

**Pendiente:** ejecutar tests adversariales, revisar implementaciones `AUTH_POST_PATHS` y `advisory_financial_prefreeze`, y presentar hallazgos confirmados y parche solo si procede.


## Revisión final del alcance implementado — 29/10/2026

**Resultado del HEAD `5beb7afb0e7770e64797a276ad3f3ac4153b5864`:** [Required CI #539](https://github.com/MarianoSevilla/fiscal-cripto-/actions/runs/40859356687) SUCCESS: backend 2.210 PASS / 63 SKIP / 16 subtests PASS; PostgreSQL y browser-navigation PASS. La suite general no equivale a una auditoría de todos los endpoints mutables.

**Cambios realmente implementados:**
- `sensitive_admin_origin_boundary` intercepta exclusivamente `POST/PATCH/PUT/DELETE` bajo `/api/admin/recursos/solicitudes/` y `/api/admin/contactos/`.
- Rechaza `Origin` externo, `Sec-Fetch-Site` igual a `cross-site` o `same-site`, y solicitudes sin `Origin` que tampoco declaren `Sec-Fetch-Site: same-origin`. **No hay excepción para solicitudes sin ambas cabeceras.**
- Las peticiones con `Origin` idéntico a `request.host_url` o con `Sec-Fetch-Site: same-origin` pueden llegar a los controles de autenticación/autorización. La comprobación se aplica *antes* de los handlers y no altera webhooks/pagos.
- Pruebas sintéticas incluyen administrador autenticado, subdominio `same-site`, origen externo, cabeceras ausentes, ruta legítima; las pruebas existentes de administración de recursos/contactos envían metadatos de navegador del mismo origen.

**Compatibilidad contrastada con código de frontend:** `static/admin-contactos.html` realiza `fetch('/api/admin/contactos/<id>', {method:'PATCH', ...})` y `static/admin-recursos.html` utiliza rutas relativas `/api/admin/recursos/solicitudes/... ` para POST/DELETE. La estructura es de mismo origen, sin dependencia observada de llamadas cruzadas. La ejecución Chromium global pasó, pero **no se afirma una sesión administrativa E2E real en Chromium**.

**Límites y riesgo residual:**
- No es un token CSRF universal ni una prueba de seguridad de todas las operaciones mutables del proyecto. Las rutas de autenticación, asesoramiento, cuenta y pagos siguen bajo sus controles propios y requieren valoraciones separadas.
- Las cabeceras de origen no son prueba de autorización: un cliente no navegador puede falsificarlas; las sesiones, roles y permisos siguen siendo obligatorios.
- La compatibilidad con navegadores/clientes que omitan ambas cabeceras no está garantizada para estas operaciones; se ha elegido el rechazo por defecto como condición de seguridad.
- No hubo pruebas sobre datos reales ni despliegue. No declarar producción protegida por este cambio hasta fusionar de forma autorizada y verificar Railway.

**Conclusión de revisión de PR #160:** modificación acotada y CI satisfactoria; apta para solicitar autorización de integración, **sin afirmar que la auditoría CSRF global está cerrada**.
