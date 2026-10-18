# Acceso, registro y recuperación — diseño aprobado e integración

Base: main e60f49e07aafdd5d7f0e599c9eecaad5a9ed903a. El 18/10/2026 el titular aprueba las cinco vistas y autoriza integrarlas en las rutas definitivas y validar el flujo antes de publicar. Producción sigue pendiente de autorización.

## Diseño

Cinco vistas: login, registro, recuperación, nueva contraseña y verificación. Sistema tipográfico, verde, controles y foco del Home; cabecera y pie compactos para tareas de autenticación. Inputs de 16 px, errores junto al campo y aviso global accesible, mostrar/ocultar contraseña, estados de espera/error/éxito y foco gestionado. Se mantienen nombre, email y contraseña de registro; ninguna funcionalidad fiscal cambia.

En escritorio se incorpora una columna visual con Bitcoin, XRP, XLM, Bitvavo y Binance. Los logos son decorativos, sin enlaces de acceso a exchanges ni afiliación implícita. El retrato de Mariano es el WebP existente del Home, fijo. La entrada animada termina antes de cinco segundos y se desactiva con movimiento reducido; en <=900 px la columna visual se oculta. No hay librería de animación ni fuentes externas.

Los tres SVG de criptomonedas proceden de spothq/cryptocurrency-icons (svg/color/btc.svg, xrp.svg y xlm.svg), licencia CC0 incluida en static/auth-assets/LICENSE-CC0.txt. Se inspeccionaron: sin scripts, eventos ni enlaces externos. Los logos de exchanges ya estaban en el repositorio. CC0 no implica respaldo ni licencia sobre marcas.

## Cambios de autenticación en la rama, todavía sin producción

- Destino next validado en servidor y navegador; persiste entre formularios, Google y enlaces de verificación/recuperación. Google conserva Authlib y sus validaciones OIDC existentes, sin autoenlazar cuentas por email.
- Identificador Flask-Login v1 con HMAC que depende de usuario y credenciales. Cambiar/restablecer contraseña invalida sesiones y remember tokens anteriores sin migración de base de datos. No expone hash de contraseña ni subject de Google en la cookie.
- En una futura publicación, las cookies antiguas con ID numérico quedarán inválidas: se requerirá un nuevo inicio de sesión una vez. No se eliminan cuentas ni se cambian sus contraseñas.
- El login por contraseña no crea sesión hasta verificar el email. Las cuentas existentes verificadas conservan sus contraseñas, incluso si son anteriores al mínimo nuevo.
- Nuevas contraseñas: mínimo 15 caracteres, máximo 72 bytes UTF-8 por la implementación bcrypt existente. Error explícito en vez de excepción/HTTP500; no se truncan ni se cambia el algoritmo ni las dependencias. Se conserva bcrypt coste12 y el esquema de hashes existente. No se promete soporte de 64 caracteres Unicode de varios bytes bajo este límite.
- Registro y reenvío no revelan por texto/código HTTP el estado de una cuenta; no se afirma igualdad temporal perfecta del envío síncrono de correo. Una carrera de email único se resuelve sin crear cuentas duplicadas.
- Consumo de token de recuperación mediante actualización condicional; el segundo uso falla. Sesiones de cuentas desactivadas se rechazan.
- Los POST de autenticación rechazan origen externo declarado, Sec-Fetch-Site cross-site y JSON/tipos malformados. Se conserva SameSite y el resto de controles. No se presenta esto como auditoría completa de CSRF para el resto de la aplicación.
- Los límites existentes siguen activos y ahora tienen mensaje específico de acceso. No se ha cambiado REDIS_URL ni se ha certificado el almacenamiento compartido de contadores en producción.

## Aislamiento y publicación posterior

scripts/build_auth_preview.py genera las cinco páginas definitivas, sus variantes *_apple.html y auth-apple-preview/ con CSS/JS inline y assets del propio origen. El viewer no inicia sesiones, no crea cuentas, no envía formularios ni abre Google: las acciones indican que es una vista previa. El autocompletado de contraseñas se desactiva solo en el viewer. Todas las páginas de autenticación y viewers son noindex,nofollow.

Promoción preparada: login.html, signup.html, forgot-password.html, reset-password.html y verify-email.html; nueva ruta pública /recuperar-contrasena. La QA de navegador utiliza ahora las rutas definitivas. Se añade una prueba integrada de registro, correo de verificación, acceso, solicitud de recuperación, consumo de token y cierre de sesión usando Flask real, plantillas de correo reales, transporte Resend interceptado y SQLite temporal sin red. CI debe pasar sobre este nuevo commit antes de solicitar publicación. La PR sigue en borrador hasta esa autorización.

## Validación y límites

Pruebas nuevas de Flask/bcrypt en proceso aislado con SQLite temporal, credenciales ficticias y red/DNS prohibidos: revocación en dos sesiones/remember, cuentas no verificadas, identidad manipulada/antigua/desactivada, límites Unicode, contraseñas existentes, errores de tipos, origen y destinos. Se actualizan las fixtures que inyectaban IDs numéricos para usar identidades firmadas reales; no se añaden excepciones de autenticación para tests.

Navegador CI: cinco vistas en 13 anchuras, campos/landmarks/ausencia de overflow, imágenes, errores locales, mostrar contraseña, respuestas429 sin falso éxito, registro y reenvío, next seguro, texto200%, movimiento reducido y fallback sin JS. Las respuestas API son sintéticas; las escrituras y destinos externos no simulados fallan. Las suites previas de Google/OIDC, navegación, backend y PostgreSQL se conservan. Los resultados ejecutados se registran en la PR; esta cobertura no anticipa su éxito.

No se prueban cuentas reales, entrega real de correo, Google con identidad real, Safari/iOS físico, penetración completa ni tasa de conversión. No hay cambios en pagos/FIFO, Railway, variables, bases de producción o dependencias. No se promete MFA, passkeys ni certificación de seguridad.
