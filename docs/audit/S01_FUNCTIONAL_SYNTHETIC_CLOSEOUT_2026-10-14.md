# S01 — Validación funcional con datos sintéticos (14/10/2026)

## Decisión: fase de código/CI; laboratorio real continúa bloqueado

S01 ya mantiene la web privada funcionando con commit exacto \`446470e121d66f240d1ea75a8c0e103e193d13c2\`; esquema de Postgres-Im3h verificado G04 READ ONLY. **No abrir aún /api/login, /api/analizar, /api/descargar, /dashboard ni rutas administrativas sobre Railway**: el login, la telemetría FIFO, la gestión C1 y la descarga de PDF tienen efectos de escritura y/o archivo. Postgres-Im3h real conserva un recurso de negocio y no es un espacio desechable para usuarios ficticios.

### Contrato validable sin efectos externos

El nuevo ejecutor de GitHub Actions \`tests/qa_s01_functional_synthetic_ci.py\` se añade exclusivamente al workflow ya existente de PR #90. Se niega a arrancar fuera de GITHUB_ACTIONS/CI/FLASK_ENV=testing o cuando existen DATABASE_URL/RAILWAY_ y secretos externos.

- Crea tablas/cuentas .invalid y un expediente ficticio únicamente en SQLite temporal mediante \`qa_flask_navigation.real_flask()\`; no usa Postgres Railway ni datos del propietario/usuarios.
- Comprueba autenticación real por contraseña, rechazo de credenciales incorrectas, identidad y roles, dashboard protegido.
- Genera desde bytes locales un CSV Bitvavo ficticio (compra/venta BTC); POST real \`/api/analizar\`, registro FifoReport, token PDF, RLS para otro usuario, descarga PDF de un solo uso.
- Comprueba API interna de asesor: listado según rol, token CSRF, rechazo de escrituras sin token, nota, cambio permitido a \`under_review\`, denegación de estado \`paid\`.
- Verifica cierre financiero C1/PREFREEZE en rutas de envío de presupuesto/inicio de pago.
- Con \`socket.connect\`, \`requests.Session.request\` y \`resend.Emails.send\` bloqueados por parches de prueba, certifica que el flujo ejercitado no utiliza red externa ni Resend.
- Comprueba contra el guard puro \`lab_request_denial\` que el laboratorio real **sigue cerrado** salvo GET/HEAD /healthz.

### Puertas de cierre

1. Obtener pipeline CI completo Python/PG18/Chromium **SUCCESS sobre SHA definitivo**, sin relajar aserciones ni despliegues.
2. Inspeccionar evidencias y clasificar fallos o advertencias nuevas si los hubiera.
3. Documentar en PR #90 la diferencia entre commit preparado y commit **actualmente desplegado**, que sigue fijado al anterior.
4. Para permitir pruebas HTTP funcionales en Railway es imprescindible otra arquitectura de **datos desechables y totalmente segregados** (DB y almacenamiento PDF), política de endpoints mínima, autenticación de operador y barreras de salida. No habilitar rutas funcionales en Postgres-Im3h por el mero hecho de aprobar CI. Cualquier nuevo despliegue exige un GO específico.
5. Ningún cambio a \`main\`, producción, staging, PayPal, Stripe, MERU, correos o facturas.

**Estado de partida:** código/CI solamente. No escrito en Railway, no nuevo DDL real, ningún servicio nuevo.
