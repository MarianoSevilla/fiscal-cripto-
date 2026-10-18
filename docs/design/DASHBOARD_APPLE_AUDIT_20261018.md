# Auditoría y propuesta: Mi espacio fiscal

Base comprobada: main3155e4119dbbf95fd539051d29a49e1893cd4f6b. Los hashes Git de app.py,auth.py,dashboard.html,nav.js y landing_apple.js locales coinciden con ese árbol. Se revisaron ramas y PR abiertas: los borradores antiguos de diseño/seguridad no son la fuente vigente. Este trabajo parte exclusivamente de main. No se fusiona ni se publica.

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
| Planes |No hay ruta Flask /pricing,aunque el menú la muestra al admin | Ocultar ese destino roto solo en esta variante; sin alterar privilegios ni sistemas de cobro |
| Stats-v2 |Prototipo administrativo con fixture según su contrato de código | No presentarlo como producto operativo |
| Historial de informes |El dashboard no dispone de una API de archivos/resultados para un historial del usuario | No inventar informes guardados,estadísticas,saldos ni actividad |

Fuentes: fiscal_app_export/app.py (rutas dashboard,me,exchanges,analizar,api_modelo_721,advisory y administración); auth.py; static/dashboard.html; static/nav.js; static/modelo721.html; advisory_prefreeze.py; communications/routes.py. No se consulta la BD real ni variables de entorno.

## Problemas priorizados

| Gravedad | Evidencia y causa | Tratamiento |
|---|---|---|
| Alta,contenido |El721 afirma funcionar con cualquier exchange; motor/selector tienen límites reales | Texto acotado sin tocar el motor ni sus reglas |
| Media,seguridad de interfaz |El guard propio convierte cualquier error de /api/me en redirección a login,confundiendo conexión y sesión caducada | Estados separados; herramientas ocultas hasta comprobar sesión; servidor sigue exigiendo login |
| Media,navegación |Menú enlaza /pricing sin ruta; opciones útiles de cuenta/ayuda son poco visibles | No promocionar el enlace roto en esta variante; accesos de apoyo con destinos reales |
| Media,rendimiento |nav.js y dashboard.html consultan /api/me por separado | Promise opcional SiteNav.ready,con estado y2flags sin datos personales,reutilizando una sola petición |
| Media,consistencia |Fondo oscuro,Syne/DM Sans remotas,radio12px y tokens propios frente al sistema aprobado | Reutilizar nav.css,landing_apple.css,landing_apple.js y footer/header del Home; solo CSS local de disposición |
| Media,accesibilidad |Buscador sin label explícito,botón×,filtros sin estado anunciado,exchanges inactivos a baja opacidad,ausencia de skip-link | Label,búsqueda con contador role=status,botón textual Limpiar,teclado/foco y solo herramientas operativas |
| Baja,claridad |Dashboard es un término técnico; la página solo dice seleccionar exchange y el721 queda antes sin contexto | Mi espacio fiscal: nombre español centrado en la tarea; URL /dashboard intacta |
| Baja,contenido |Bybit/Más exchanges inactivos y footer©2025 | Retirar la promoción de herramientas no operativas,conservar el footer aprobado con año dinámico |

No se presenta el cambio del límite del login de PR113 como resolución de la demora: ese diagnóstico sigue pendiente y fuera del alcance de esta propuesta.

## Diseño y alcance

Nombre recomendado: **Mi espacio fiscal**. «Panel de control» describe administración; «Mis informes» implicaría un archivo de resultados que no se ofrece. La nueva variante cambia su título y la etiqueta del menú solo en esta página; no cambia la URL original ni las etiquetas del resto de páginas.

Intro,tipografía,anchura1160px,espaciado responsive,paleta verde,controles y tarjetas proceden del sistema aprobado. Dos accesos de tarea (FIFO/721) preceden al selector de11exchanges; el primero lleva y da foco al selector de la misma página. Búsqueda local sin cargas ni envíos. Cuenta,recursos y consulta fiscal como apoyo. Gestión aparece solo para perfiles autorizados. Ayuda y footer conservan el estándar. No se introducen gráficos,cifras de uso ni decoraciones sin función.

La propuesta no sustituye las pantallas internas de cálculo: son destinos existentes. No se prueba ni afirma completada una renovación de esas pantallas ni una auditoría fiscal/normativa de sus textos. Las suites previas de motores/API siguen formando parte de CI.

## Seguridad y roles

La variante se sirve desde templates/dashboard_apple.html en /dashboard-apple-preview con login_required,limiter.exempt,no-store y noindex,nofollow. El /dashboard original y su HTML se conservan. No se crea un endpoint que permita forjar roles ni sesiones. El viewer público usa identidades ficticias y bloquea APIs y enlaces privados (también al abrir otra pestaña o sinJS).

nav.js conserva sus decisiones de rol y añade un contrato opcional: SiteNav.ready devuelve únicamente state,is_admin,is_fiscal_advisor. No entrega nombre,email,NIF ni plan a consumidores. Las decisiones de navegación conservan los flags que /api/me calcula en el servidor,incluido el respaldo autorizado por emails de configuración. Un plan pro no hace administrador a un usuario; admin/free mantiene los accesos administrativos existentes.

La zona Gestión copia las opciones ya admitidas por el menú y añade /admin/contactos solo si is_admin. **Discrepancia preexistente:** el servidor permite /admin/recursos a asesores,aunque el menú solo lo muestra a admin. Se documenta y conserva esa política de visualización; no se amplían privilegios ni se modifica auth.py. /mis-solicitudes-fiscales sigue siendo solo admin (404 para otros). Comunicaciones conserva su denegación404 y demás endpoints mantienen sus403/redirecciones.

El cliente no es una barrera de autorización. Se prueban solicitudes directas a páginas/API con cookies de prueba firmadas y planes/perfiles distintos,así como cookies antiguas,falsificadas y cuenta desactivada. Las herramientas sin sesión rechazan antes de procesar archivos. El nuevo HTML no incluye datos del usuario y no está publicado como archivo estático accesible sin login.

## Validación y evidencia

Pruebas nuevas,pendientes de resultado final en la PR:

- Proceso Flask real sin red/DNS,entorno de prueba sin secretos heredados,SQLite temporal: roles×planes,11destinosFIFO,721,cuenta,solicitud,backups de rol por email,API directas,restricciones administrativas,revocación y cabeceras de preview. No se ejecutan operaciones reales ni se utilizan ficheros de usuarios.
- Navegador local de CI:3roles en13anchuras,búsquedaUnicode/vacía,contadores,teclado,menúdesktop/móvil,una única petición de sesión,estados anónimo/error/lento,noJS,texto200%,movimiento reducido,assets locales y viewer aislado.
- Capturas antes/después,390/768/1280px y menús/estados. La captura de referencia anterior conserva el HTML original; las fuentes externas se interceptan en CI,por lo que su tipografía de respaldo no acredita una carga real de Google Fonts.
- Se mantienen Required CI,regresión backend,PostgreSQL y suites anteriores. Los resultados ejecutados y enlaces de run/artefactos se registran en la PR; no se presupone su éxito.

Límites: sin cuentas reales,BD real,Google/email reales,Safari físico,medición de conversión,pentest integral ni certificación WCAG. No se garantiza latencia de cálculo a partir de una vista previa. Antes de publicar: revisión visual del titular,CI final y promoción explícita de la variante a la ruta original. Publicación y fusión requieren autorización separada.

## Archivos afectados

app.py (solo ruta de variante),static/nav.js (contrato opcional),templates/dashboard_apple.html,static/dashboard_apple.css,static/dashboard_apple.js,scripts/build_dashboard_preview.py,dashboard-apple-preview/index.html y pruebas/documentación. static/dashboard.html,auth.py,motoresFIFO/721,dependencias,workflows,pagos,Railway y variables se conservan.
