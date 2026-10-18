# Auditoría y propuesta: Mi espacio fiscal

Base comprobada: main `3155e4119dbbf95fd539051d29a49e1893cd4f6b`. Se revisaron ramas y PR abiertas: los borradores antiguos de diseño/seguridad no son la fuente vigente. La primera propuesta aislada fue validada en `b497f22` y aprobada visualmente. La revisión posterior prepara su promoción a `/dashboard` en la misma PR #114, todavía en borrador. No se fusiona ni se publica; la producción conserva el dashboard anterior.

## Funcionalidades y restricciones comprobadas en código

| Acceso | Situación actual | Decisión en la propuesta |
|---|---|---|
| FIFO |11 rutas autenticadas: Binance,Bit2Me,Bitget,Bitvavo,Coinbase,Crypto.com,Kraken,KuCoin,MEXC,Nexo,Uphold | Mantener las11, búsqueda local, enlace a la herramienta existente de cada exchange |
| Formatos FIFO |MEXC requiere XLS/XLSX; KuCoin/Bitget tienen vías multiarchivo; Bit2Me Excel depende de un flag | Describir MEXC correctamente y dejar cada instrucción/validación en su herramienta vigente; no activar flags |
| Modelo721 |/modelo721 y APIs autenticadas;9 motores compatibles, Bit2Me con respuesta informativa; KuCoin no está en el selector | Acceso propio y texto de borrador condicionado a datos completos; no prometer compatibilidad universal ni presentación oficial |
| Cuenta |/account requiere sesión; gestiona datos y acceso | Enlace directo sin copiar NIF,email o información fiscal al dashboard |
| Asesoramiento |/pedir-asesoramiento y solicitud para revisión disponibles con sesión; presupuestos y pagos suspendidos | Permitir consulta para revisión y explicar la suspensión; sin importe,pago,plazo o promesa de contratación |
| Guías/recursos |Biblioteca y documentación públicas existentes | Enlaces de apoyo, sin duplicar funcionalidades |
| Gestión |Panel de asesoramiento,stats,comunicaciones,recursos,solicitudes y contactos tienen protecciones de servidor diferentes | Mantener las opciones del menú por perfil; añadir Contactos solo a admin en la zona de gestión |
| Planes |No hay ruta Flask /pricing,aunque el menú la muestra al admin | Retirar el enlace y su activación desde nav.js compartido; sin crear servicios ni alterar privilegios o cobros |
| Stats-v2 |Prototipo administrativo con fixture según su contrato de código | No presentarlo como producto operativo |
| Historial de informes |El dashboard no dispone de una API de archivos/resultados para un historial del usuario | No inventar informes guardados,estadísticas,saldos ni actividad |

Fuentes: fiscal_app_export/app.py (rutas dashboard,me,exchanges,analizar,api_modelo_721,advisory y administración); auth.py; static/dashboard.html; static/nav.js; static/modelo721.html; advisory_prefreeze.py; communications/routes.py. No se consulta la BD real ni variables de entorno.

## Problemas priorizados

| Gravedad | Evidencia y causa | Tratamiento |
|---|---|---|
| Alta,contenido |El721 afirma funcionar con cualquier exchange; motor/selector tienen límites reales | Texto acotado sin tocar el motor ni sus reglas |
| Media,seguridad de interfaz |El guard anterior del dashboard convierte cualquier error de /api/me en redirección a login; el header compartido muestra acceso anónimo ante errores y el fallback del diseño añade login mientras espera | Separar carga, error, sesión anónima confirmada y sesión autenticada; reintento neutral en header y dashboard, sin redirección por error; servidor sigue exigiendo login |
| Media,navegación |Menú enlaza /pricing sin ruta; opciones útiles de cuenta/ayuda son poco visibles | Retirar Planes en la navegación compartida; accesos de apoyo con destinos reales |
| Media,rendimiento |nav.js y dashboard.html consultan /api/me por separado | Promise opcional SiteNav.ready,con estado y2flags sin datos personales,reutilizando una sola petición |
| Media,consistencia |Fondo oscuro,Syne/DM Sans remotas,radio12px y tokens propios frente al sistema aprobado | Reutilizar nav.css,landing_apple.css,landing_apple.js y footer/header del Home; solo CSS local de disposición |
| Media,accesibilidad |Buscador sin label explícito,botón×,filtros sin estado anunciado,exchanges inactivos a baja opacidad,ausencia de skip-link | Label,búsqueda con contador role=status,botón textual Limpiar,teclado/foco y solo herramientas operativas |
| Baja,claridad |Dashboard es un término técnico y las etiquetas de acceso no son consistentes | Mi espacio fiscal en página, menú compartido y enlaces pertinentes de Modelo 721 y asesoramiento; URL /dashboard intacta |
| Baja,contenido |Bybit/Más exchanges inactivos y footer©2025 | Retirar la promoción de herramientas no operativas,conservar el footer aprobado con año dinámico |

No se presenta el cambio del límite del login de PR113 como resolución de la demora: ese diagnóstico sigue pendiente y fuera del alcance de esta propuesta.

## Diseño y alcance

Nombre aprobado: **Mi espacio fiscal**. «Panel de control» describe administración; «Mis informes» implicaría un archivo de resultados que no se ofrece. La denominación se aplica en el menú compartido y en los enlaces que identifican el destino. Los textos de acción «Cambiar» y «Analizar otro exchange» se conservan porque describen la tarea y no nombran otra página. No se cambia ninguna URL.

Intro,tipografía,anchura1160px,espaciado responsive,paleta verde,controles y tarjetas proceden del sistema aprobado. Dos accesos de tarea (FIFO/721) preceden al selector de11exchanges; el primero lleva y da foco al selector de la misma página. Búsqueda local sin cargas ni envíos. Cuenta,recursos y consulta fiscal como apoyo. Gestión aparece solo para perfiles autorizados. Ayuda y footer conservan el estándar. No se introducen gráficos,cifras de uso ni decoraciones sin función.

La propuesta no sustituye las pantallas internas de cálculo: son destinos existentes. No se prueba ni afirma completada una renovación de esas pantallas ni una auditoría fiscal/normativa de sus textos. Las suites previas de motores/API siguen formando parte de CI.

## Seguridad y roles

La ruta definitiva `/dashboard` pasa a servir `templates/dashboard_apple.html` con los mismos `login_required`, `limiter.exempt` y `strict_slashes=False`, y añade `no-store` y `noindex,nofollow`. `/dashboard-apple-preview` conserva los enlaces de revisión y devuelve la misma página protegida. `static/dashboard.html` se conserva únicamente como referencia histórica; la ruta definitiva ya no lo sirve. No se crea un endpoint que permita forjar roles ni sesiones. El viewer público usa identidades ficticias y bloquea APIs y enlaces privados (también al abrir otra pestaña o sin JS).

nav.js conserva sus decisiones de rol y añade un contrato opcional: SiteNav.ready devuelve únicamente state,is_admin,is_fiscal_advisor. No entrega nombre,email,NIF ni plan a consumidores. Las decisiones de navegación conservan los flags que /api/me calcula en el servidor,incluido el respaldo autorizado por emails de configuración. Un plan pro no hace administrador a un usuario; admin/free mantiene los accesos administrativos existentes.

La comprobación compartida solo considera anónima una respuesta válida y explícita `{user:null}`. HTTP fallido, red, JSON inválido o esquema inesperado dejan el acceso sin comprobar. El encabezado ofrece «Reintentar», conserva la navegación pública y no muestra avatar, privilegios ni enlaces de acceso anónimo como si conociera la sesión. Tras ocho segundos pendientes ofrece esperar o reintentar. El reintento recarga la página; no cierra sesión ni borra cookies. Se retira el fallback duplicado de landing_apple.js que añadía enlaces de login durante la espera. La composición y el estilo aprobados en los estados normales se conservan.

La zona Gestión copia las opciones ya admitidas por el menú y añade /admin/contactos solo si is_admin. **Discrepancia preexistente:** el servidor permite /admin/recursos a asesores,aunque el menú solo lo muestra a admin. Se documenta y conserva esa política de visualización; no se amplían privilegios ni se modifica auth.py. /mis-solicitudes-fiscales sigue siendo solo admin (404 para otros). Comunicaciones conserva su denegación404 y demás endpoints mantienen sus403/redirecciones.

El cliente no es una barrera de autorización. Se prueban solicitudes directas a páginas/API con cookies de prueba firmadas y planes/perfiles distintos,así como cookies antiguas,falsificadas y cuenta desactivada. Las herramientas sin sesión rechazan antes de procesar archivos. El nuevo HTML no incluye datos del usuario y no está publicado como archivo estático accesible sin login.

## Validación y evidencia

La validación inicial de `b497f22` terminó con Required CI SUCCESS: backend 1945 passed/63 skipped, PostgreSQL PASS y dashboard 60 escenarios PASS. La revisión de promoción requiere repetir Required CI sobre su nuevo commit; el resultado final y el enlace de ejecución se registran en la PR.

Cobertura de la revisión:

- Proceso Flask real sin red/DNS,entorno de prueba sin secretos heredados,SQLite temporal: roles×planes,11destinosFIFO,721,cuenta,solicitud,backups de rol por email,API directas,restricciones administrativas,revocación y cabeceras de preview. No se ejecutan operaciones reales ni se utilizan ficheros de usuarios.
- Navegador local de CI: ruta definitiva `/dashboard`, 3 roles en 13 anchuras, búsqueda Unicode/vacía, contadores, teclado, menú desktop/móvil, una única petición de sesión, estados anónimo/error/lento, sin JS, texto 200%, movimiento reducido, assets locales y viewer aislado.
- Regresión compartida: nombre y ausencia de Planes en Home, Herramientas, Exchanges, Modelo 721 y dashboard; fallos HTTP/red/JSON/esquema en Home, Exchanges y dashboard; recuperación mediante reintento. Las pruebas del Home comprueban la espera neutral y la restitución del foco tras confirmar la sesión.
- Capturas antes/después,390/768/1280px y menús/estados. La captura de referencia anterior conserva el HTML original; las fuentes externas se interceptan en CI,por lo que su tipografía de respaldo no acredita una carga real de Google Fonts.
- Se mantienen Required CI,regresión backend,PostgreSQL y suites anteriores. Los resultados ejecutados y enlaces de run/artefactos se registran en la PR; no se presupone su éxito.

Límites: sin cuentas reales, BD real, Google/email reales, Safari físico, medición de conversión, pentest integral ni certificación WCAG. No se garantiza latencia de cálculo a partir de una vista previa. No se renuevan los guards ni los formularios internos de las herramientas fiscales. Antes de publicar: CI final y autorización expresa de fusión y publicación. El diseño está aprobado y no se modifica su composición.

## Archivos afectados

Implementación inicial: app.py, static/nav.js, templates/dashboard_apple.html, static/dashboard_apple.css, static/dashboard_apple.js, scripts/build_dashboard_preview.py, dashboard-apple-preview/index.html y pruebas/documentación.

Revisión de coherencia y promoción: app.py (ruta definitiva y alias), nav.js/nav.css (nombre, retirada de Planes y estados de acceso), landing_apple.js (retirada de fallback duplicado), dashboard_apple.js (retirada de excepciones locales), modelo721.html y asesoramiento-fiscal.html (solo caption de enlace), generador/viewer y pruebas/documentación. static/dashboard.html, auth.py, motores FIFO/721, dependencias, workflows, pagos, Railway y variables se conservan.
