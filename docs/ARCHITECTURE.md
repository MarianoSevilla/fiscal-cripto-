# ARCHITECTURE.md
### Fotografía técnica del sistema — estado real, no estado ideal

## 0. Vigencia

- Creado: 2026-06-25. Última revisión: 2026-06-28.
- Se revisa cuando cambia un componente, un proveedor, un patrón de integración, el
  esquema de base de datos, o el stack tecnológico. No se revisa cuando se añade un
  exchange nuevo con el mismo patrón, una página nueva con el mismo stack, o cualquier
  cambio funcional que no altere la arquitectura.
- Cualquier afirmación de este documento debe poder responderse "sí, podemos demostrarlo
  leyendo el repositorio y el sistema hoy". Si la respuesta es no, la afirmación no
  pertenece aquí.

---

## 1. Propósito de este documento

Este documento describe el estado técnico real del sistema tal como existe en la fecha
de la última revisión. No contiene principios de trabajo, criterios fiscales, decisiones
de negocio, ni arquitectura deseable. Esos contenidos pertenecen, respectivamente, a
`ENGINEERING_PRINCIPLES.md`, `PROJECT_IDENTITY.md`, y `docs/decisions/`.

Responde a:

- ¿Qué componentes existen y qué hace cada uno?
- ¿Cómo fluyen los datos de extremo a extremo?
- ¿Qué depende de qué?
- ¿Con qué tecnologías está construido y por qué cada una está ahí?
- ¿Cómo se despliega, configura y persiste?
- ¿Dónde falla o se queda corto el sistema hoy?

Si este documento afirma algo que contradice el estado actual del código, el documento
está desactualizado — no el código. Excepción: cuando la discrepancia afecte al
resultado del cálculo fiscal, no debe resolverse automáticamente asumiendo que el
código es la fuente de verdad. Esa discrepancia debe escalarse al gobierno del proyecto
definido en `PROJECT_IDENTITY.md` §5.

---

## 2. Vista general del sistema

El sistema es una aplicación web Flask de una sola instancia desplegada en Railway. No
hay microservicios, colas asíncronas ni frontend desacoplado: el mismo proceso Python
sirve el HTML, las APIs y los ficheros estáticos.

**Capas:**

```
Navegador del usuario
        │  HTTP/HTTPS
        ▼
  Gunicorn (gthread, 1 worker, 8 threads)
        │
  Flask app  ──── static/  (HTML, JS, CSS — servidos directamente)
        │
  ┌─────┼──────────────────────────────────────┐
  │     │                                       │
Clasificadores  Motor FIFO  Generadores de salida
(por exchange)    (cálculo)   (PDF, XML 721)
  │                                             │
  └─────────────────────────────────────────────┘
        │
  PostgreSQL (Railway managed)
        │
  Servicios externos:
    Resend (email) · CoinGecko/BCE (precios) · Google OAuth
    PayPal / Stripe (pagos) · Cloudflare Turnstile (spam)
```

**Líneas del ecosistema y su implementación técnica:**

| Línea | Implementación |
|-------|---------------|
| Herramienta FIFO (informe PDF) | `clasificador_*.py` → `motor_fifo.py` → `generador_pdf.py` |
| Herramienta Modelo 721 (XML AEAT) | `clasificador_*.py` → `motor_fifo.py` → `modelo721.py` → `generador_xml_721.py` |
| Asesoramiento fiscal humano | Modelos `FiscalAdvisoryRequest/*` + PayPal/Stripe + panel admin |
| Recursos educativos | Modelos `Resource`/`ResourceRequest` + páginas estáticas |

**Frontend:** HTML/JS/CSS sin build step ni bundler. El proceso Flask sirve tanto
ficheros estáticos desde `static/` (`send_from_directory`) como páginas renderizadas
con Jinja2 desde `templates/` (`render_template`).

**Dos patrones de template para las páginas de exchange (coexisten actualmente):**

| Patrón | Template | Exchanges que lo usan | Estado |
|--------|----------|-----------------------|--------|
| **Standalone** (nuevo estándar) | `[exchange]_v1.html` — autocontenido, sin variables Jinja2. El contexto del usuario se obtiene vía `/api/me` en el cliente. | Binance (`binance_v2.html`) | Estándar para cualquier exchange nuevo |
| **Genérico** (legacy) | `tool.html` — template Jinja2 con variables inyectadas desde `EXCHANGE_PAGES` en `app.py`. | Bitvavo, Bit2Me, Kraken, Coinbase, Nexo, Crypto.com, Uphold, MEXC, Bitget, KuCoin | Vigente para los exchanges existentes; no se usa para exchanges nuevos |

La decisión de adoptar el patrón standalone está documentada en
`docs/decisions/ADR-0002-exchange-template-standalone.md`.

---

## 3. Stack tecnológico

Cada tecnología se lista con su justificación arquitectónica dentro del sistema.

| Tecnología | Por qué está aquí |
|-----------|------------------|
| **Python 3.13.13** (pinned en `.python-version`) | Lenguaje único del backend. La versión está fijada exactamente para garantizar reproducibilidad entre entorno local y Railway. |
| **Flask** | Framework web principal. El ORM, el panel de administración y la autenticación se construyen directamente sobre él con librerías individuales, sin un framework full-stack. |
| **Flask-SQLAlchemy** | ORM que abstrae la diferencia entre SQLite (desarrollo) y PostgreSQL (producción). Permite usar los mismos modelos sin cambio de código entre entornos. |
| **Flask-Login** | Gestión de sesión de usuario autenticado. Proporciona `current_user`, `@login_required` y las cookies "remember me" sin reimplementar el ciclo de vida de sesión. |
| **Flask-Bcrypt** | Hash de contraseñas con bcrypt, cost factor 12. La elección de bcrypt (vs. argon2 u otras) no está documentada como ADR; es la implementación vigente. |
| **Flask-Limiter** | Rate limiting por usuario autenticado (user_id) o por IP (anónimo). Soporta backend en memoria o Redis según `REDIS_URL`. |
| **Flask-CORS** | Política CORS explícita (whitelist). Sin esta extensión, Flask no restringe orígenes por defecto. |
| **Flask-Compress** | Compresión gzip de respuestas HTTP. Reduce tráfico para páginas HTML grandes. |
| **Flask-Migrate** | Gestión de migraciones de esquema via Alembic. Canal formal de evolución del esquema. |
| **Authlib** | Flujo OIDC de Google OAuth. Maneja el intercambio de tokens y la validación del id_token sin código manual. |
| **itsdangerous** | Tokenización firmada de un solo uso con expiración — sin persistencia en DB. Usado para verificación de email y borrado de cuenta. |
| **requests** | Cliente HTTP para las APIs de CoinGecko y BCE. No hay cliente específico para estas APIs. |
| **Resend** | Envío de email transaccional (verificación, reset de contraseña, notificaciones de asesoramiento). SDK oficial de Resend para Python. |
| **psycopg2-binary** | Adaptador PostgreSQL para SQLAlchemy. La versión `-binary` incluye las dependencias nativas sin compilación en Railway. |
| **ReportLab** | Generación de PDFs en el servidor. No hay navegador headless implicado; el PDF se construye programáticamente con primitivas de layout. |
| **matplotlib** | Generación de gráficos dentro del PDF (gráfico de resultados fiscales). La imagen se renderiza en memoria y se incrusta en el documento ReportLab. |
| **pandas** | Lectura y manipulación de CSVs. Proporciona detección de encoding y manejo de tipos de columna. |
| **openpyxl + xlrd** | Lectura de ficheros Excel (`.xlsx` y `.xls` legacy). Necesarios para MEXC y Bit2Me Excel. |
| **Gunicorn** | Servidor WSGI en producción. Worker class `gthread` — los threads comparten memoria dentro del mismo proceso, lo que permite el lock de análisis concurrente y los contadores de rate limiting sin Redis. Los parámetros de despliegue concretos están en §10. |
| **Stripe** | Procesador de pagos secundario (advisory). Importado con try/except; la aplicación arranca sin él. |
| **xmlschema** | Validación de XML contra XSD. Utilizado para verificar el XML del Modelo 721 contra los schemas oficiales de la AEAT incluidos en el repositorio. |
| **werkzeug ProxyFix** | Middleware que adapta el entorno WSGI para funcionar correctamente detrás del reverse proxy de Railway. |

---

## 4. Flujo de datos

Los recorridos descritos a continuación son a nivel de componentes, no de
implementación interna.

### 4.1 Generación de informe FIFO

```
Usuario sube CSV/Excel
    │  POST /api/analizar  (o /api/kucoin/analizar, /api/bitget/analizar)
    ▼
Validación de entrada
    │  extensión + tamaño (≤15 MB global) + contenido + match de exchange
    ▼
Clasificador del exchange
    │  parsea filas → lista de operaciones normalizadas
    ▼
_pipeline_motor(clasificador) → MotorFIFO
    │  procesa operaciones en orden cronológico
    │  aplica filtro por ejercicio fiscal
    ▼
Generador PDF
    │  construye documento en memoria → tmpfile en disco
    ▼
Token (hex 32 bytes) almacenado en cookie de sesión firmada (TTL 5 min)
    │
    ▼  GET /api/descargar/<token>
Validación del token (sesión, propiedad, TTL)
    │
    ▼
PDF enviado al navegador → fichero eliminado de disco
    │
    ▼
FifoReport (metadata) escrito en DB — sin PDF
```

### 4.2 Modelo 721

```
Usuario sube CSV del exchange
    │  POST /api/721
    ▼
Clasificador del exchange → MotorFIFO
    ▼
generar_datos_modelo_721()
    │  snapshot de posición a 31/12 del ejercicio
    ▼
enriquecer_721_con_precios()
    │  CoinGecko (por activo cripto) → precio EUR a 31/12
    │  BCE (fallback para stablecoins USD → EUR/USD)
    ▼
validar_para_xml()
    │  capa técnica: XSD oficial AEAT
    │  capa estructural: campos completos, sin placeholders
    │  capa fiscal: custodios identificados, precios disponibles
    │  → ValidacionXML (estado: BLOQUEADO / BORRADOR / VÁLIDO)
    ▼
JSON de respuesta (datos + estado de validación)
    │
    ▼  POST /api/721/xml  (si el usuario solicita el XML)
generar_xml_721() → XSD validation → bytes XML devueltos
    │
    ▼
Log estructurado M721 emitido
```

### 4.3 Solicitud de asesoramiento fiscal

```
Usuario rellena formulario
    │  POST /api/asesoramiento/solicitar
    ▼
FiscalAdvisoryRequest creada en DB  (status: "submitted")
    │
    ├── Email de confirmación al usuario (Resend)
    └── Notificación interna a admin (Resend)
              │
              ▼  (acción manual del admin)
Admin revía caso → envía presupuesto
    │  POST /api/admin/asesoramiento/solicitudes/{id}/enviar-presupuesto
    ▼
Token de pago generado → link enviado al usuario (Resend)
    │
    ▼  (acción del usuario)
Usuario paga vía PayPal o Stripe
    │  GET /pagar/<token> → POST /api/pago/iniciar/<token>
    ▼
Webhook PayPal / Stripe confirma pago
    │  POST /api/webhooks/paypal  |  /api/webhooks/stripe
    ▼
Estado actualizado → notificación interna
```

### 4.4 Autenticación de usuario

```
── Email/contraseña ──────────────────────────────────────────────────
POST /api/login
    │  bcrypt.check_password_hash(hash, input)
    │  Flask-Login: login_user(user, remember=...)
    ▼
Cookie de sesión (ephemeral) + cookie remember-me (30d, si marcado)

── Google OAuth ──────────────────────────────────────────────────────
GET /auth/google
    │  Authlib genera redirect → Google OIDC
    ▼
GET /auth/google/callback
    │  Authlib valida id_token
    │  Busca usuario por google_id o email → crea si no existe
    │  Flask-Login: login_user(user)
    ▼
Cookie de sesión
```

### 4.5 Administración

```
Acceso a /admin/*  o  /api/admin/*
    │  @require_admin_page  (página: redirect a /dashboard si falla)
    │  @require_admin       (API: 403 JSON si falla)
    ▼
Comprobación de rol:
    1. user.role == 'admin' en DB
    2. Fallback: user.email en ADMIN_EMAILS (env var)
    ▼
Panel de gestión: asesoramiento, contactos, recursos, comunicaciones,
    errores de procesamiento, campañas de email
```

---

## 5. Componentes críticos y dependencias

| Componente | Responsabilidad principal | Consumidores | Depende de | Criticidad |
|-----------|--------------------------|-------------|-----------|-----------|
| `motor_fifo.py` | Cálculo FIFO de ganancias y pérdidas patrimoniales. Mantiene el inventario de lotes. | `app.py` (todos los flujos de análisis), `modelo721.py` | Ninguno externo | **Alta** — todo resultado fiscal depende de él |
| `clasificador_*.py` (13 ficheros) | Parseo del fichero de cada exchange y normalización a operaciones que el motor entiende | `app.py` (funciones `procesar_*`) | `motor_fifo.py` (estructura de datos `Lote`) | **Alta** — sin clasificador no hay entrada al motor |
| `generador_pdf.py` | Generación del informe FIFO en formato PDF para autogestión del usuario | `app.py`, `generador_pdf_bitget.py`, `generador_pdf_mexc.py` | `motor_fifo.py` (`ResultadoFIFO`, `ResumenActivo`), matplotlib, ReportLab | **Alta** — documento de salida principal de la herramienta FIFO |
| `modelo721.py` | Snapshot de posición de activos a 31/12 y estructura de datos del Modelo 721 | `app.py` (flujo 721), `generador_xml_721.py` | `motor_fifo.py` (inventario, resultados) | **Alta** — determina qué activos entran en la declaración |
| `generador_xml_721.py` | Generación del XML y validación de las tres capas (técnica, estructural, fiscal) | `app.py` | `modelo721.py`, `custodios_721.py`, XSD schemas en disco | **Alta** — documento formal ante la AEAT |
| `precios_historicos.py` | Precios EUR de activos a 31/12 de cada ejercicio, consultando CoinGecko y BCE | `app.py` (`enriquecer_721_con_precios`) | CoinGecko API (externa), BCE Data API (externa) | **Media-Alta** — un fallo de precio bloquea el estado VÁLIDO del XML |
| `custodios_721.py` | Catálogo estático de identificadores fiscales de custodios extranjeros | `generador_xml_721.py` | Ninguno | **Media** — un custodio sin identificador produce BORRADOR en lugar de VÁLIDO |
| `models.py` | Definición del esquema de base de datos (SQLAlchemy) | `app.py`, `auth.py`, `error_tracking.py`, `communications/` | Flask-SQLAlchemy | **Alta** — toda la persistencia del sistema pasa por aquí |
| `auth.py` | Comprobación centralizada de roles y decoradores de autorización | `app.py` (todos los endpoints protegidos) | Flask-Login, `models.py` | **Media-Alta** — protege todos los endpoints de admin y asesor fiscal |
| `error_tracking.py` | Registro best-effort de errores de procesamiento de CSV; sanitización de PII antes de persistir | `app.py` (captura de errores en análisis) | `models.py`, email (Resend) | **Baja** — best-effort; nunca bloquea el flujo principal |
| `communications/` (blueprint Flask) | Gestión de campañas de email masivas y seguimiento de entregas individuales | `app.py` (registra el blueprint) | `models.py` (`CommunicationCampaign`, `CommunicationDelivery`), Resend | **Baja-Media** — un fallo afecta a comunicaciones de marketing; no al cálculo fiscal ni al Modelo 721 |
| `app.py` | Orquestación de todos los flujos, definición de rutas Flask, configuración de extensiones | Frontend (HTTP), todos los demás componentes | Todos los anteriores | **Alta** — punto de entrada único del sistema |

---

## 6. Ingesta de datos externos

**Exchanges soportados:**

_Esta sección se actualiza cada vez que se incorpora una nueva fuente de datos o cambia el estado de verificación de una existente._

| Exchange | Formato | Módulo parser | Datos reales verificados | Notas |
|---------|---------|--------------|------------------------|-------|
| Binance | CSV "Transaction History" (formato legacy) | `clasificador.py` | Sí | |
| Binance | CSV "Transaction History" (formato post-2022) | `clasificador_binance_tx.py` | Sí | Detección automática en `_detectar_formato_binance()` |
| Bitvavo | CSV | `clasificador_bitvavo.py` | Sí | |
| Bit2Me | CSV "Informe Fiscal" | `clasificador_bit2me.py` | Sí | |
| Bit2Me | Excel "Historial de operaciones" | `clasificador_bit2me_excel.py` | Sí | Feature flag `BIT2ME_EXCEL_ENABLED` — desactivado en producción |
| Kraken | CSV "Ledgers" (no "Trades") | `clasificador_kraken.py` | Sí | |
| Coinbase | CSV | `clasificador_coinbase.py` | Sí | |
| Nexo | CSV | `clasificador_nexo.py` | Sí | |
| Crypto.com | CSV | `clasificador_cryptocom.py` | Sí | |
| Uphold | CSV | `clasificador_uphold.py` | Sí | |
| MEXC | XLS / XLSX | `clasificador_mexc.py` | Sí | Único exchange con entrada en formato Excel nativo |
| Bitget | CSV spot (soporta múltiples ficheros) | `clasificador_bitget.py` + `ClasificadorBitgetMulti` | Sí | Endpoint dedicado `/api/bitget/analizar` |
| KuCoin | CSV (soporta múltiples ficheros) | `clasificador_kucoin.py` | Sí (producción) / No (tests) — ver §15 | Solo spot trading en fase 1; endpoint dedicado `/api/kucoin/analizar` |

**Patrón de incorporación de una nueva fuente:**

*Backend:* cada exchange tiene un módulo `clasificador_*.py` independiente. El módulo
declara una clase que valida las columnas esperadas al instanciarse y normaliza las
filas a las operaciones que `MotorFIFO` reconoce (`registrar_compra`,
`registrar_venta`, `registrar_swap`). El motor no conoce el origen; la frontera entre
clasificador y motor es la API del motor.

*Frontend:* a partir de 2026-06-28, cada exchange nuevo recibe su propia plantilla
HTML standalone (`[exchange]_v1.html`), duplicada de `binance_v2.html` y adaptada
según `docs/DESIGN_SYSTEM.md §13`. La ruta Flask usa `render_template("[exchange]_v1.html")`
directamente, sin variables Jinja2. El proceso completo está en `docs/EXCHANGE_IMPLEMENTATION_GUIDE.md`.

**Detección de formato:** cada clasificador verifica las columnas esperadas al
instanciarse y lanza una excepción específica si el fichero no coincide. El endpoint
de análisis para Binance ejecuta `_detectar_formato_binance()` antes de elegir el
clasificador.

---

## 7. Motor de cálculo fiscal

- **Método:** FIFO estricto (First In, First Out), art. 37.2 LIRPF.
- **Precisión numérica:** `float` nativo de Python — no se usa `decimal.Decimal` en
  este componente.
- **Tipos de operación reconocidos:** compra, venta, swap (cripto-a-cripto), rendimiento
  (staking, intereses, rebates). Los rendimientos no entran al inventario FIFO.
- **Stablecoins:** `USDC, USDT, BUSD, FDUSD, DAI` — tratadas como equivalentes 1:1 EUR
  en ausencia de precio de mercado real en el momento del intercambio.
- **Swaps sin inventario previo:** el coste base del activo recibido se fija a cero; se
  registra una advertencia en `motor.advertencias`. El resultado fiscal de ese swap marca
  `inventario_incompleto = True`.
- **Trazabilidad:** cada `ResultadoFIFO` contiene `lotes_consumidos` con el detalle de
  qué lotes del inventario se consumieron para producir ese resultado.
- **Período de generación:** calculado como días desde la fecha del lote más antiguo
  consumido hasta la fecha de venta/swap. Se informa en el PDF pero no altera el
  tratamiento fiscal (en España, corto y largo plazo van a la base del ahorro).
- **Snapshot de inventario:** `snapshot_inventario(fecha_corte)` devuelve el estado del
  inventario en una fecha dada sin modificar el inventario activo del motor.

---

## 8. Documentos de salida

### 8.1 Informe FIFO (PDF)

- **Generado por:** `generador_pdf.py` (función `generar_pdf()`). Los módulos
  `generador_pdf_bitget.py` y `generador_pdf_mexc.py` son thin wrappers (32-33 líneas)
  que llaman a `generar_pdf()` con el nombre del exchange correspondiente.
- **Librería:** ReportLab. Generación enteramente server-side sin navegador headless.
- **Contenido:** portada con KPIs fiscales, resumen ejecutivo, tabla de ventas y
  permutas por ejercicio, lista de rendimientos, sección de advertencias del motor,
  posición actual del inventario.
- **Limitaciones comunicadas al usuario:** las advertencias del motor se muestran en
  sección dedicada del PDF. Las operaciones con `inventario_incompleto = True` se
  señalan por operación en la tabla de detalle.
- **Almacenamiento:** el PDF no se guarda en base de datos ni en disco de forma
  persistente. Se genera en un fichero temporal del sistema operativo, se sirve una sola
  vez al navegador, y se elimina inmediatamente tras la descarga. El token de descarga
  se almacena en la cookie de sesión firmada (TTL 5 minutos, vinculado al `user_id`).
- **Límites de rendering:** las celdas de tabla se truncan ante contenido anómalamente
  largo para prevenir errores de layout de ReportLab.

### 8.2 XML Modelo 721

- **Generado por:** `generador_xml_721.py` (función `generar_xml_721()`).
- **Validación en tres capas independientes:**
  1. *Técnica*: el XML está bien formado y valida contra los XSD oficiales de la AEAT.
  2. *Estructural*: todos los campos obligatorios contienen datos reales (sin
     placeholders ni identificadores `PENDIENTE`).
  3. *Fiscal*: custodios identificados con confianza media o alta, precios históricos
     disponibles para todos los activos, sin advertencias críticas del motor.
- **XSD schemas:** `Declaracion721.xsd`, `DeclaracionInformativa721.xsd`,
  `RespuestaDeclaracion721.xsd` — incluidos en el repositorio en
  `fiscal_app_export/`. La validación se ejecuta localmente sin dependencia de red.
- **Estados del XML:**

  | Estado | `xml_generable` | `es_borrador` | Significado |
  |--------|:-:|:-:|---|
  | `BLOQUEADO` | `False` | — | Sin precio para algún activo, o NIF del declarante inválido. No se puede generar el XML. |
  | `BORRADOR` | `True` | `True` | XML generado pero con datos incompletos o sin verificar. No presentar sin resolver los pendientes. |
  | `VÁLIDO` | `True` | `False` | Todos los datos presentes y verificados. El usuario debe revisar antes de firmar y presentar. |

- **El estado "pasa XSD" nunca equivale a "listo para presentar".** El sistema no
  colapsa las tres capas de validación.

---

## 9. Autenticación y gestión de usuarios

**Mecanismos activos:**

- **Email/contraseña:** hash bcrypt, cost factor 12, implementado con Flask-Bcrypt.
  Las cuentas creadas vía Google OAuth no tienen `password_hash` (campo `None`).
- **Google OAuth:** flujo OIDC via Authlib. Activo solo si `GOOGLE_CLIENT_ID` y
  `GOOGLE_CLIENT_SECRET` están presentes en el entorno. Si faltan, el botón de Google
  no aparece; la aplicación arranca sin error.

**Sesión:**

- Flask-Login gestiona el ciclo de vida del usuario autenticado.
- Cookie de sesión: ephemeral (sin `Max-Age`), destruida al cerrar el navegador.
  `Secure`, `HttpOnly`, `SameSite=Lax` en producción (`FLASK_ENV=production`).
- Cookie "Recordarme": TTL 30 días, mismas flags de seguridad.

**Verificación de email:**

- Token firmado con itsdangerous (`URLSafeTimedSerializer`). El token codifica el email
  y lleva timestamp; no se almacena en DB. Enviado via Resend al registrarse.

**Restablecimiento de contraseña:**

- Token aleatorio (32 bytes hex, `secrets.token_hex(32)`). Su hash SHA-256 se almacena
  en `users.password_reset_token_hash`. La expiración se guarda en
  `users.password_reset_expires_at`.

**Roles:**

| Rol | Acceso |
|-----|--------|
| `user` | Herramienta FIFO, Modelo 721, asesoramiento (solicitante), recursos |
| `fiscal_advisor` | Todo lo anterior + panel de gestión de asesoramiento |
| `admin` | Todo lo anterior + gestión de usuarios, campañas, contactos, recursos |

**Comprobación de rol:** fuente primaria = campo `role` en la tabla `users`; fallback =
email del usuario en `ADMIN_EMAILS` o `FISCAL_ADVISOR_EMAILS` (variables de entorno).
El fallback es un mecanismo de compatibilidad hacia atrás documentado como en transición
en `auth.py` ("Fase 1").

**Decoradores de autorización:** `@require_admin` (API → HTTP 403 JSON si falla),
`@require_admin_page` (página → redirect a `/dashboard` si falla). Equivalentes para
`fiscal_advisor`.

---

## 10. Infraestructura

| Servicio | Proveedor | Función |
|---------|-----------|---------|
| Plataforma de despliegue | Railway | Hosting del proceso Flask + variables de entorno + red |
| Base de datos | PostgreSQL gestionada por Railway | Persistencia de todos los datos del sistema |
| Servidor WSGI | Gunicorn (gthread, 1 worker, 8 threads, timeout 120s) | Servidor de producción; arranca tras `flask db upgrade` (Procfile) |
| Email transaccional | Resend | Verificación de email, reset de contraseña, notificaciones de asesoramiento |
| Pagos | PayPal (primario) + Stripe (secundario) | Cobro de servicios de asesoramiento fiscal |
| Precios históricos | CoinGecko API + BCE Data API | Valoración de activos a 31/12 para el Modelo 721 |
| Antispam | Cloudflare Turnstile | Formulario de contacto |
| Proxy | Railway (actúa como reverse proxy) | Termina TLS; ProxyFix middleware en el proceso Flask |

---

## 11. Configuración

**Variables fail-fast (el proceso no arranca sin ellas en producción):**

| Variable | Comportamiento sin ella |
|---------|------------------------|
| `SECRET_KEY` | `RuntimeError` en arranque si `FLASK_ENV=production`. En desarrollo, usa clave insegura con aviso. |

**Variables requeridas (el sistema funciona degradado sin ellas):**

| Variable | Sin ella |
|---------|---------|
| `DATABASE_URL` | Fallback a SQLite local (`fiscal_users.db`). No aceptable en producción. |
| `RESEND_API_KEY` | Emails no se envían. El sistema no falla, pero el flujo de verificación y asesoramiento queda roto. |
| `RESEND_FROM_EMAIL` | Usa `noreply@marianosevilla.com` por defecto. |
| `APP_BASE_URL` | Los links en emails apuntan a `https://www.marianosevilla.com` por defecto. |
| `GOOGLE_CLIENT_ID` + `GOOGLE_CLIENT_SECRET` | Google OAuth desactivado silenciosamente. El botón de Google no aparece en el frontend. |

**Feature flags (desactivados por defecto):**

| Variable | Activa |
|---------|--------|
| `BIT2ME_EXCEL_ENABLED=true` | Soporte del Excel "Historial de operaciones" de Bit2Me como entrada al motor. |
| `ENABLE_ADVISORY_UPLOADS=true` | Subida de ficheros adjuntos a solicitudes de asesoramiento. Desactivado porque el filesystem local de Railway no es persistente entre deploys. |
| `ENABLE_ADVISORY_STATUS_EMAILS=true` | Emails automáticos al usuario al cambiar el estado de su solicitud de asesoramiento. |
| `PROCESSING_ERROR_EMAILS_ENABLED=true` | Emails automáticos al detectar errores de procesamiento de CSV. |

**Variables opcionales de ajuste:**

| Variable | Defecto | Función |
|---------|---------|---------|
| `REDIS_URL` | — | Backend de rate limiting compartido entre workers. Sin ella, el limiter usa memoria local (un set por proceso). |
| `COINGECKO_API_KEY` | — | Si presente, usa la API Pro de CoinGecko (límite mayor). Sin ella, usa free tier con throttle de 1.2s/req. |
| `PAYPAL_ENVIRONMENT` | `sandbox` | `sandbox` o `live`. |
| `PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET`, `PAYPAL_WEBHOOK_ID` | — | PayPal desactivado si ausentes. |
| `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET` | — | Stripe desactivado si ausentes. |
| `ADMIN_EMAILS` | — | Lista CSV de emails con acceso admin (fallback; fuente primaria es el campo `role` en DB). |
| `FISCAL_ADVISOR_EMAILS` | — | Lista CSV de emails con acceso de asesor fiscal (fallback). |
| `FISCAL_ADVISORY_NOTIFY_EMAILS` | — | Emails que reciben notificaciones de nuevas solicitudes de asesoramiento. |
| `FISCAL_ADVISORY_BASIC_PRICE` | — | Precio en céntimos del servicio de revisión básica. Obligatorio si el servicio de asesoramiento está activo. |
| `FISCAL_ADVISORY_ADVANCED_PRICE` | — | Precio en céntimos del servicio de revisión avanzada. Obligatorio si el servicio de asesoramiento está activo. |
| `FISCAL_ADVISORY_COMPLEX_PRICE` | — | Precio en céntimos de la valoración inicial de caso complejo. Obligatorio si el servicio de asesoramiento está activo. |
| `PROCESSING_ERROR_MAX_EMAILS_PER_HOUR` | `100` | Límite de emails automáticos de error por hora. |
| `FLASK_ENV` | — | `production` activa fail-fast de `SECRET_KEY` y flags `Secure` en cookies. |

---

## 12. Persistencia de datos

**Motor de base de datos:** PostgreSQL en producción (Railway gestionado). SQLite como
fallback en desarrollo local (fichero `fiscal_users.db` en `fiscal_app_export/`).

**Gestión de migraciones:** Flask-Migrate (Alembic). El historial de migraciones está en
`fiscal_app_export/migrations/versions/`. El comando `flask db upgrade` se ejecuta
automáticamente en cada despliegue (Procfile, antes de arrancar Gunicorn). Existe
además un bloque bootstrap en el arranque de `app.py` que ejecuta `ALTER TABLE IF NOT
EXISTS` para columnas añadidas fuera del canal de migraciones formal (ver sección 15).

**Tablas y ciclo de vida de sus datos:**

| Tabla | Nace | Se transforma | Muere |
|-------|------|--------------|-------|
| `users` | Registro vía `/api/register` o callback OAuth | Actualizaciones de perfil, verificación email, cambio de contraseña, actualización de rol | Cuando el usuario solicita borrado vía `/api/delete-account` |
| `fifo_reports` | Al completar (o fallar) un análisis FIFO | `downloaded_at` se rellena al descargar | No se borran automáticamente |
| `processing_errors` | Al producirse un error de procesamiento de CSV | `resolved` se marca manualmente por admin | No se borran automáticamente |
| `contactos` | Al enviar el formulario de contacto | `estado` y `archived_at` se actualizan por admin | No se borran automáticamente |
| `fiscal_advisory_requests` | Al enviar solicitud de asesoramiento | Cambios de estado a lo largo del ciclo de vida del caso | No se borran automáticamente (sí por acción admin explícita) |
| `fiscal_advisory_files` | Al subir un fichero adjunto (feature flag) | — | Al borrar la solicitud (cascade) |
| `fiscal_advisory_status_history` | Al cambiar el estado de una solicitud | — | Al borrar la solicitud (cascade) |
| `advisory_internal_notes` | Al añadir una nota interna por admin/asesor | — | Al borrar la solicitud (cascade) |
| `advisory_audit_log` | Al ejecutar una acción admin registrable | — | `request_id` puede quedar como NULL si la solicitud se borra |
| `communication_campaigns` | Al crear una campaña de email | Estado actualizado durante el envío | No se borran automáticamente |
| `communication_deliveries` | Al encolar el envío a cada destinatario | `status` y `sent_at` actualizados al enviar | No se borran automáticamente |
| `resources` | Al crear un recurso educativo (admin) | Actualizaciones de contenido y estado | No se borran automáticamente |
| `resource_requests` | Al enviar solicitud de acceso a un recurso | `status` actualizado por admin | No se borran automáticamente (sí por acción admin explícita) |

**Datos transitorios (no persisten en DB):**

- El **PDF generado** vive solo en un fichero temporal del sistema operativo. Muere
  cuando el usuario descarga (inmediatamente tras el envío) o cuando expira el token
  (5 minutos, pero el fichero solo se elimina en la próxima petición — no hay limpieza
  proactiva programada).
- El **token de descarga del PDF** vive en la cookie de sesión firmada (Flask session).
  Muere al consumirse o al expirar.
- Los **datos de CoinGecko/BCE** para el Modelo 721 se obtienen en tiempo de petición
  y no se cachean en DB; cada sesión 721 los vuelve a pedir.

**Ficheros adjuntos de asesoramiento:** almacenados en `uploads/advisory/` en el
filesystem local del proceso Railway. Railway no garantiza persistencia del filesystem
entre deploys. La tabla `fiscal_advisory_files` tiene columnas `storage_provider` y
`storage_key` presentes pero ignoradas por el código actual (ver sección 16).

---

## 13. Observabilidad y telemetría

**Lo que se registra:**

| Qué | Dónde | Qué datos contiene |
|----|-------|-------------------|
| Metadatos de informes FIFO generados | `fifo_reports` (DB) | exchange, ejercicio, tiempo de procesamiento, contadores de operaciones/swaps/rendimientos/advertencias, resultado neto, estado (generated/failed) |
| Errores de procesamiento de CSV | `processing_errors` (DB) | exchange, etapa del error, tipo de excepción, categoría, fingerprint, nombre y tamaño del fichero (sin contenido), traceback truncado a 1500 chars |
| Eventos del Modelo 721 | Log estructurado `M721` (stdout Railway) | exchange, ejercicio, estado XML, número de activos, xml_generable, tickers sin precio, número de custodios sin id, número de bloqueantes y advertencias, total EUR aproximado |
| Acciones admin sobre solicitudes | `advisory_audit_log` (DB) | request_id, admin_id, acción, detalle, timestamp |
| Campañas de email | `communication_campaigns` + `communication_deliveries` (DB) | estado del envío, errores por destinatario |

**Lo que explícitamente NO se registra:**

- NIF del declarante.
- Nombre del declarante.
- Cantidades de activos individuales.
- Precios individuales por activo.
- Operaciones detalladas del CSV.
- El XML generado del Modelo 721.
- El contenido de los CSV o Excel subidos por el usuario.

La sanitización de errores en `error_tracking.py` aplica redacción activa de emails,
tokens y credenciales antes de persistir cualquier texto de excepción.

**Métricas de negocio:** disponibles en tiempo real para admin via `GET /api/stats`.

---

## 14. Seguridad

Los vectores listados aquí son los identificados y demostrados como reales en este
sistema. No es una lista genérica de buenas prácticas.

**Vectores identificados y su estado:**

| Vector | Mitigación activa | Estado |
|--------|------------------|--------|
| Upload de fichero muy grande o comprimido | `MAX_CONTENT_LENGTH = 15 MB` en Flask (corta antes de llegar a la aplicación). El riesgo de fichero comprimido con bomba queda reducido pero no eliminado dentro del límite de 15 MB. | Activo |
| Path traversal en tokens de descarga | El token es `secrets.token_hex(32)` — sin paths, sin separadores de directorio. El endpoint `/api/descargar/<token>` solo sirve ficheros cuyo nombre coincide exactamente con el token en sesión. | Resuelto |
| PDF token compartido entre workers Gunicorn | Migrado de dict en memoria local a cookie de sesión firmada (itsdangerous). El token viaja con el usuario independientemente del worker que atienda la petición. | Resuelto |
| PII en logs de error de procesamiento | `error_tracking.py` aplica redacción activa (regex) de emails, tokens, y credenciales antes de persistir en DB. | Activo |
| Secreto de sesión sin configurar en producción | `SECRET_KEY` ausente con `FLASK_ENV=production` → `RuntimeError` en arranque (fail-fast). | Resuelto |
| Análisis concurrente del mismo usuario | `_analisis_en_curso: set` + lock de threading. Evita que el mismo usuario_id lance dos análisis simultáneos. Efectivo dentro de un mismo proceso (1 worker actual). | Activo — limitado a 1 worker |

**Políticas activas:**

- CORS: orígenes explícitos (`marianosevilla.com`, `www.marianosevilla.com`,
  `fiscal.marianosevilla.com`). Métodos permitidos: GET, POST, OPTIONS.
- Security headers: `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`,
  `Referrer-Policy: strict-origin-when-cross-origin`, HSTS, CSP parcial. Aplicados
  en el hook `after_request`.
- Rate limiting por usuario_id (autenticado) o por IP (anónimo), con umbrales
  configurados en `app.py`. Admins exentos en endpoints de análisis.
- Sesión: `Secure`, `HttpOnly`, `SameSite=Lax` en producción.
- Validación de fichero subido: extensión + tamaño + contenido + coincidencia con el
  exchange declarado. El análisis de contenido se hace leyendo las columnas esperadas
  del clasificador, no el MIME type del fichero.

---

Las tres secciones siguientes (15, 16 y 17) documentan el estado activo del sistema en
el momento de la última revisión. Cuando una entrada se resuelve, se elimina de la
sección correspondiente. Si la resolución implica una decisión arquitectónica, se
registra en un ADR en `docs/decisions/`.

## 15. Desviaciones respecto a ENGINEERING_PRINCIPLES.md

| Desviación | Principio afectado | Causa | Estado |
|-----------|-------------------|-------|--------|
| Tests de KuCoin usan fixtures sintéticas, no CSV reales del exchange | Principio 2: "Ninguna fuente de datos externa nueva se incorpora sin datos reales de esa fuente para probarla" | La fase 1 de KuCoin se desarrolló antes de recibir los CSV reales (pendientes de Rafa, según memoria del proyecto, 2026-06-24) | Pendiente de resolución |
| Ficheros `app_old.py`, `clasificador_bit2me_old.py`, `clasificador_bitvavo_old.py`, `generador_pdf_old.py` presentes en la rama principal | Principio 14: "El código que ya no se usa no permanece indefinidamente en la rama principal" | Archivos de respaldo de versiones anteriores, no eliminados | Pendiente de resolución |
| Bloque bootstrap de `ALTER TABLE IF NOT EXISTS` en el arranque de `app.py` coexiste con las migraciones Alembic | Principio 4 (implícito): dos mecanismos de gestión de esquema crean incertidumbre sobre qué estado real tiene la DB | Parche de emergencia para columnas añadidas durante incidentes; nunca formalizado como migración | Activo |

---

## 16. Deuda técnica

| Deuda | Impacto |
|-------|---------|
| `app.py` concentra rutas, configuración, helpers, lógica de negocio y orquestación de todos los flujos en un único fichero, sin separación de responsabilidades | Cualquier cambio en cualquier área del sistema requiere trabajar en el mismo fichero. La búsqueda de una función en contexto es costosa. El riesgo de colisión entre cambios paralelos es alto. |
| Rate limiting en memoria local por proceso | En la configuración actual (1 worker Gunicorn), no hay impacto. Si se escala a múltiples workers sin configurar `REDIS_URL`, cada worker llevaría sus propios contadores independientes y el límite efectivo se multiplicaría por el número de workers. |
| Concurrent analysis lock en memoria local por proceso | Mismo problema que el rate limiting: la protección contra análisis simultáneos del mismo usuario no es efectiva entre workers distintos. |
| Transición de roles no completada — fallback activo a env vars | La migración al campo `role` en DB como única fuente de autorización está documentada en `auth.py` como "Fase 1" pero no se ha completado. Mientras el fallback a `ADMIN_EMAILS`/`FISCAL_ADVISOR_EMAILS` esté activo, el sistema tiene dos fuentes de autorización que pueden producir resultados distintos si no están alineadas. |
| Ficheros adjuntos de asesoramiento en filesystem local | `fiscal_advisory_files` persiste referencias a ficheros en `uploads/advisory/`. El filesystem local de Railway no sobrevive un redeploy. Los modelos tienen `storage_provider` y `storage_key` preparados para almacenamiento externo, pero el código de lectura/escritura de ficheros ignora esas columnas. |
| `generador_pdf.py` sin separación entre API pública e implementación interna | `generador_pdf_bitget.py` y `generador_pdf_mexc.py` son thin wrappers que llaman directamente a `generar_pdf()`. No hay contrato formal entre el generador y sus consumidores más allá de la firma de la función. |
| Bloque `ALTER TABLE IF NOT EXISTS` en el arranque de `app.py` sin migración Alembic equivalente | Las columnas añadidas por este mecanismo no tienen migración formal. Si una instancia arranca sin ejecutar ese bloque de startup, puede quedar en un estado de esquema diferente al que el código espera. El mecanismo correcto es una migración Alembic. |

---

## 17. Limitaciones conocidas de la arquitectura

Las siguientes son restricciones inherentes al diseño actual que no constituyen ni
una desviación de principios ni deuda técnica en el sentido estricto. Son aceptables
en el contexto actual del sistema.

| Limitación | Por qué es aceptable hoy |
|-----------|------------------------|
| Todo el cómputo (FIFO, 721, precios) es síncrono en el hilo de la petición HTTP | El volumen de usuarios actual y el tiempo de procesamiento observado (milisegundos para la mayoría de CSVs) no justifican la complejidad de un sistema de colas asíncronas. |
| CoinGecko free tier: 1.2 s de throttle entre requests al pedir precios del Modelo 721 | Consecuencia directa del plan gratuito. Un Modelo 721 con 10 activos tarda ~12 s en obtener precios. Para el volumen actual, no es un problema de experiencia de usuario bloqueante. |
| El PDF no se almacena: no hay historial de informes descargables para el usuario | Decisión consciente documentada en el código: reduce el riesgo de almacenar datos fiscales en disco. El usuario puede regenerar el informe subiendo el mismo CSV. |
| No hay aislamiento de datos entre usuarios a nivel de base de datos (no hay Row-Level Security en PostgreSQL) | El aislamiento depende de la lógica de aplicación (Flask-Login + comprobación de `user_id`). Para el modelo actual (un solo tenant lógico, sin datos compartidos entre usuarios) es suficiente. |
| No hay API pública documentada | Los endpoints `/api/*` están diseñados para ser consumidos exclusivamente por el frontend propio. No hay contrato de compatibilidad hacia atrás ni versionado de API. |
| Los precios de CoinGecko para el Modelo 721 no se cachean en DB entre sesiones | Cada sesión del Modelo 721 vuelve a pedir los precios a CoinGecko. Para el volumen actual, el coste de repetir las peticiones es menor que la complejidad de gestionar una caché de precios históricos con invalidación. |

---

## 18. Decisiones arquitectónicas vigentes

Las decisiones listadas aquí son reconstruidas del código y sus comentarios. Su
contexto, alternativas y justificación formal pertenecen a los ADRs en `docs/decisions/`
(ver sección 21).

| Decisión | Consecuencias que condicionan el resto del documento |
|---------|-----------------------------------------------------|
| **Arquitectura monolítica: un único proceso Flask para todas las líneas del ecosistema** | El mismo proceso sirve HTML, APIs, ficheros estáticos y todos los componentes. No hay microservicios ni frontend desacoplado. |
| **Un proceso Flask con gthread (1 worker, 8 threads)** en lugar de múltiples workers | Consecuencia directa de la arquitectura monolítica con estado en memoria. El concurrent analysis lock y el rate limiting son coherentes dentro del proceso. Escalar a múltiples workers requiere mover ese estado a Redis. |
| **PDF efímero: no almacenado en DB ni en disco de forma persistente** | El usuario no tiene historial de informes descargables. Cada análisis requiere subir el CSV de nuevo. |
| **Clasificador por exchange como módulo independiente; motor FIFO exchange-agnóstico** | El motor no conoce el origen de los datos. Los cambios en el formato de un exchange solo tocan su clasificador. El motor se puede probar de forma independiente. |
| **Generadores PDF por exchange como thin wrappers sobre un generador compartido** | `generador_pdf_bitget.py` y `generador_pdf_mexc.py` delegan en `generar_pdf()` sin modificarlo. Añadir un nuevo exchange no requiere tocar el generador compartido. |
| **Plantillas HTML standalone por exchange como nuevo estándar de frontend** | A partir de 2026-06-28, cada exchange nuevo recibe su propia plantilla HTML en lugar de usar `tool.html` con variables Jinja2. Los exchanges existentes (10) siguen usando `tool.html` como patrón legacy. Ver `docs/decisions/ADR-0002`. |
| **XSD schemas de la AEAT incluidos en el repositorio** | La validación del XML del Modelo 721 no depende de conectividad de red en tiempo de ejecución. Los schemas son los publicados por la AEAT en el procedimiento GI55. |
| **Validación del Modelo 721 en tres capas independientes** | "Pasa el XSD" no equivale a "listo para presentar". Las tres capas producen el estado BLOQUEADO/BORRADOR/VÁLIDO. Esta separación está documentada en detalle en `fiscal_app_export/ARCHITECTURE.md`. |
| **Dual-source para comprobación de roles (DB + env vars)** | El sistema tiene dos fuentes de autorización activas: el campo `role` en DB (primaria) y las env vars `ADMIN_EMAILS`/`FISCAL_ADVISOR_EMAILS` (fallback). Pueden producir resultados distintos si no están alineadas. La transición para eliminar el fallback está pendiente (ver sección 16). |
| **Bootstrap de emergencia `ALTER TABLE IF NOT EXISTS` al arrancar** | Coexiste con las migraciones Alembic. Es deuda técnica activa (ver sección 16). |

**ADRs relacionados**

- [ADR-0001](decisions/ADR-0001-monolito-flask.md) — Arquitectura monolítica del sistema.
- [ADR-0002](decisions/ADR-0002-exchange-template-standalone.md) — Plantillas HTML standalone por exchange como nuevo estándar de frontend.

---

## 19. Evolución prevista de la arquitectura

Esta sección recoge únicamente direcciones técnicas ya señaladas en el código o en
sus comentarios. No incluye deseos ni recomendaciones.

| Dirección | Evidencia en el código |
|----------|----------------------|
| **Eliminación del fallback de roles a env vars** | `auth.py` nombra el estado actual como "Fase 1" y describe la fuente primaria (DB) como la definitiva. El fallback a `ADMIN_EMAILS`/`FISCAL_ADVISOR_EMAILS` es explícitamente transitorio. |
| **Migración de ficheros adjuntos de asesoramiento a almacenamiento externo** | `models.py` tiene columnas `storage_provider` y `storage_key` en `fiscal_advisory_files`. El código actual las ignora. El comentario en los modelos indica "Preparado para Fase 2 — almacenamiento externo (R2/S3/Supabase)". |
| **Shared state de rate limiting y concurrent analysis lock via Redis** | El comentario en `app.py` junto al lock es explícito: "Sin Redis: protección por proceso; para cobertura multi-worker → FASE 2B". El código de rate limiting ya soporta `REDIS_URL`. |

---

## 20. Vocabulario técnico

Términos de implementación propios de este sistema. El vocabulario de dominio fiscal
(FIFO, Modelo 721, swap, rendimiento, custodio) vive en `PROJECT_IDENTITY.md`.

| Término | Significado en este sistema |
|--------|---------------------------|
| `Clasificador*` | Clase Python que parsea el fichero exportado por un exchange y produce operaciones normalizadas consumibles por `MotorFIFO`. Hay un módulo independiente por exchange. |
| `MotorFIFO` | Objeto con estado que mantiene el inventario FIFO activo y acumula resultados fiscales a medida que se le alimentan operaciones vía `registrar_compra`, `registrar_venta`, `registrar_swap`. |
| `Lote` | Unidad de inventario FIFO: una cantidad de un activo cripto adquirida en una fecha concreta a un coste unitario determinado. |
| `ResultadoFIFO` | Resultado fiscal de una venta o swap: precio de transmisión, precio de coste FIFO de los lotes consumidos, ganancia o pérdida, lotes consumidos. |
| `ResumenActivo` | Posición actual de un activo tras todas las operaciones: cantidad total, coste total, precio medio de los lotes restantes. |
| `ValidacionXML` | Dataclass con el resultado de las tres capas de validación del Modelo 721: estado (`xml_generable`, `es_borrador`), lista de advertencias, lista de bloqueantes. |
| `FifoReport` | Registro en DB de la generación de un informe FIFO. Solo contiene metadatos; el PDF no se almacena. |
| `ProcessingError` | Registro en DB de un error de procesamiento de CSV. Incluye fingerprint de SHA-256 para deduplicación de errores recurrentes. |
| `_pipeline_motor(clasificador)` | Función en `app.py` que conecta un clasificador con el motor FIFO: crea el motor, alimenta las operaciones del clasificador, y devuelve el motor ya procesado. |
| Feature flag | Variable de entorno booleana que activa o desactiva una funcionalidad ya desplegada en el código pero no expuesta en producción. |
| `confianza_id` | Nivel de fiabilidad del identificador fiscal de un custodio en `custodios_721.py`: `alta` (fuente oficial primaria verificada), `media` (publicado por la entidad), `baja` (sin confirmar). |
| BORRADOR / BLOQUEADO / VÁLIDO | Estados del XML del Modelo 721 resultantes de aplicar las tres capas de validación. |
| `inventario_incompleto` | Flag booleano en `ResultadoFIFO`. `True` cuando la operación consumió lotes para los que no existía inventario previo suficiente; el coste base es parcial o nulo. |

---

## 21. Relación con otros documentos

| Documento | Responde a |
|-----------|-----------|
| `docs/PROJECT_IDENTITY.md` | Qué es el proyecto y por qué existe; principios fundacionales; gobierno; misión; ecosistema de servicios; vocabulario de dominio fiscal. |
| `docs/ENGINEERING_PRINCIPLES.md` | Cómo se trabaja; qué constituye un cambio terminado; auditoría obligatoria; análisis de impacto; definición de terminado. |
| `docs/decisions/` (ADRs) | Decisiones arquitectónicas puntuales con su contexto, alternativas consideradas y consecuencias. Este directorio no existe a fecha de creación de este documento. |
| `docs/audits/` | Snapshots fechados de auditorías formales antes de cambios en fuentes de datos, motor de cálculo o generadores de salida. Este directorio no existe a fecha de creación de este documento. |
| `fiscal_app_export/ARCHITECTURE.md` | Documentación técnica de detalle del módulo Modelo 721: el principio de validación en tres capas, los estados del XML, el flujo del módulo 721 y el esquema de observabilidad de ese endpoint. No está supersedido por este documento. |

**Alcance del módulo 721 entre este documento y `fiscal_app_export/ARCHITECTURE.md`:**
este documento cubre el flujo de datos, los componentes y los estados del Modelo 721 a
nivel arquitectónico. `fiscal_app_export/ARCHITECTURE.md` cubre el formato del log
`M721`, la tabla de responsabilidades de ficheros y el detalle de implementación de la
validación en tres capas — esos contenidos no se repiten aquí.

**Nota de nomenclatura:** este documento usa 'VÁLIDO' para el estado del XML del Modelo
721 con `xml_generable=True` y `es_borrador=False`. `fiscal_app_export/ARCHITECTURE.md`
usa 'LISTO' para el mismo estado. Actualmente coexisten ambos términos en la
documentación del proyecto. Hasta que un ADR unifique la nomenclatura, ambos deben
considerarse equivalentes.

**Regla de prioridad en caso de conflicto:**

- Si este documento entra en conflicto con `PROJECT_IDENTITY.md` sobre misión,
  ecosistema o gobierno: `PROJECT_IDENTITY.md` tiene prioridad.
- Si este documento afirma un estado técnico que el código contradice: este documento
  está desactualizado y debe corregirse — el código es la fuente de verdad del estado
  técnico. Excepción: si la discrepancia afecta al resultado del cálculo fiscal, debe
  escalarse al gobierno del proyecto (`PROJECT_IDENTITY.md` §5) en lugar de resolverse
  asumiendo que el código es correcto.
- Si `ENGINEERING_PRINCIPLES.md` y este documento difieren sobre si algo es un
  principio de trabajo o un hecho de arquitectura: la afirmación pertenece al documento
  que corresponde según la distinción qué/por qué/cómo (`PROJECT_IDENTITY.md`) /
  cómo trabajamos (`ENGINEERING_PRINCIPLES.md`) / qué hay construido hoy (este
  documento).
