# Auditoría de código y correspondencia con Privacidad

Fecha: 18 de octubre de 2026, Europe/Madrid. Repositorio: MarianoSevilla/fiscal-cripto-.

## Resultado y alcance

La política debe describir el funcionamiento existente, sin presentar la intención de no conservar resultados como una función ya implantada. La auditoría revisa código de `main` fijado en `bb84e75a876f936a94b80b1c6dc064e39b46afeb`. No se han consultado usuarios, informes, archivos fiscales, correos privados ni filas de producción. Tampoco se han modificado infraestructura, variables, bases de datos, pagos, seguridad o motores de cálculo.

La existencia de un modelo no demuestra que haya filas reales; un flujo que escribe en ese modelo sí demuestra el comportamiento programado cuando se ejecuta. Una ruta suspendida no se trata como un servicio activo. Esta revisión no verifica de nuevo el commit del proceso desplegado, configuraciones privadas, contratos, copias de seguridad o plazos de los proveedores. No certifica cumplimiento integral del RGPD.

## Inventario y evidencia

Los enlaces de esta tabla están fijados al commit auditado. Las referencias son a funciones o modelos completos, no a datos reales.

| Flujo | Datos y comportamiento comprobado | Evidencia |
|---|---|---|
| Registro e inicio de sesión | Nombre/email, hash de contraseña, Google ID en OAuth, fechas, estado, roles/plan y preferencias. El NIF se guarda si se facilita al perfil. El registro no comprueba edad ni recoge un consentimiento promocional separado. | [User](https://github.com/MarianoSevilla/fiscal-cripto-/blob/bb84e75a876f936a94b80b1c6dc064e39b46afeb/fiscal_app_export/models.py#L15), `register`, `login`, `auth_google_callback`, `update_profile`, `update_nif` en [app.py](https://github.com/MarianoSevilla/fiscal-cripto-/blob/bb84e75a876f936a94b80b1c6dc064e39b46afeb/fiscal_app_export/app.py) |
| CSV/Excel de análisis | Se escriben temporales en disco. Las rutas principales y multifichero intentan eliminarlos en `finally`; errores de eliminación se silencian. No equivale a procesamiento solo en memoria ni a garantía absoluta de borrado. | `analizar` (2139), `analizar_kucoin` (2554), `analizar_bitget` (2708), `api_modelo_721` (2860) en app.py |
| PDF | Se escribe a disco antes de devolver el token. Token de 300 segundos. `descargar` marca la descarga, inicia hilo con espera de dos segundos e intenta eliminar; no confirma finalización de la transferencia. No se identifica barrido general de PDF huérfanos en los flujos revisados. | `_guardar_token_pdf` (347), `_consumir_token_pdf` (355), `descargar` (3371) en app.py |
| Registro FIFO | Se guardan usuario, exchange, ejercicio, contadores, tipos de operación, tiempos, estado, fecha de descarga y resultados monetarios. No es el PDF completo, pero sí información fiscal asociada. | [FifoReport](https://github.com/MarianoSevilla/fiscal-cripto-/blob/bb84e75a876f936a94b80b1c6dc064e39b46afeb/fiscal_app_export/models.py#L51), `_registrar_informe` (460) y llamadas desde las tres rutas FIFO |
| Estadísticas | Conteos, exchanges, volumen, descargas, actividad, usuarios destacados y segmentos por complejidad/uso. Algunas consultas dependen de `user_id` y de datos de operación. Email parcialmente oculto en una vista no anonimiza la base. | `_api_stats_data` (4021) y `api_stats_v2_encuentro` en app.py |
| Diagnóstico | Se guarda usuario/email, exchange, nombre/tamaño del archivo, error, traceback limitado, huella y contexto técnico. `_capturar_evidencia` lee hash, formato, encoding y primera línea/cabeceras. Si un archivo no tiene cabecera correcta, esa primera línea podría contener valores. No se acredita envío automático del CSV completo al titular. | `_capturar_evidencia` (395), [ProcessingError](https://github.com/MarianoSevilla/fiscal-cripto-/blob/bb84e75a876f936a94b80b1c6dc064e39b46afeb/fiscal_app_export/models.py#L87), `_do_record` y `record_processing_error_safe` en [error_tracking.py](https://github.com/MarianoSevilla/fiscal-cripto-/blob/bb84e75a876f936a94b80b1c6dc064e39b46afeb/fiscal_app_export/error_tracking.py) |
| Correo por error | El registro del diagnóstico ocurre antes de comprobar la opción de email. El aviso automático depende de una variable, deduplicación y categoría. Sin leer configuración no se afirma que esté activo. | `_do_record` en error_tracking.py, opción `PROCESSING_ERROR_EMAILS_ENABLED` |
| Modelo 721 | Temporal de entrada; respuesta JSON/XML. Log de exchange, año, estado, activos y avisos; incluye `total_eur_aprox`. Excepciones pueden producir logs. No se certifica anonimización del conjunto de logs. | `api_modelo_721` (2860–3158), `api_721_xml` (3165), [precios_historicos.py](https://github.com/MarianoSevilla/fiscal-cripto-/blob/bb84e75a876f936a94b80b1c6dc064e39b46afeb/fiscal_app_export/precios_historicos.py) |
| Contacto | Persiste nombre, email, tipo, mensaje, IP y User-Agent. Notifica por Resend al destinatario configurado. Archivar modifica estado/fecha, no elimina la fila. | `api_contacto` (3944), `admin_contactos_patch` (6017), `Contacto` en models.py |
| Solicitud de recursos | Guarda nombre/email, exchange, situación en Bitvavo, UID o indicador de desconocimiento, Telegram, aceptaciones e IP. Exige marketing y UID salvo desconocimiento; no existe en este flujo una validación externa del UID con el exchange. | `resource_solicitar` (5789), [recurso.html](https://github.com/MarianoSevilla/fiscal-cripto-/blob/bb84e75a876f936a94b80b1c6dc064e39b46afeb/fiscal_app_export/templates/recurso.html), `ResourceRequest` en models.py |
| Asesoramiento: solicitud activa | Guarda identificación/contacto, residencia, ejercicio, descripción, tipologías, exchanges/volumen y facturación si se aporta. Historial, notas y notificaciones de gestión. No presupone que se haya contratado o cobrado. | `advisory_solicitar` (4808), `FiscalAdvisoryRequest`, `FiscalAdvisoryStatusHistory`, `AdvisoryInternalNote`, `AdvisoryAuditLog` |
| Asesoramiento: archivos/pagos | Nuevas cargas y flujos financieros heredados tienen decorador de suspensión incondicional. La consulta protegida de archivos anteriores no tiene ese decorador. La definición de la tabla no demuestra archivos existentes. No se presenta Stripe/PayPal como cobro activo. | `advisory_upload_file` (5542), `advisory_download_file` (5591), rutas de presupuesto/pago y [advisory_prefreeze.py](https://github.com/MarianoSevilla/fiscal-cripto-/blob/bb84e75a876f936a94b80b1c6dc064e39b46afeb/fiscal_app_export/advisory_prefreeze.py) |
| Campañas y bajas | Módulo registrado; puede seleccionar cuentas activas no dadas de baja por verificación o envío individual. No exige prueba de opt-in para seleccionar una cuenta. Guarda campañas/entregas; determinados envíos individuales no tienen token de baja. No se han consultado campañas reales. | `_base_recipients_query`, `_send_individual_no_user`, `_execute_campaign` en [communications/service.py](https://github.com/MarianoSevilla/fiscal-cripto-/blob/bb84e75a876f936a94b80b1c6dc064e39b46afeb/fiscal_app_export/communications/service.py), [routes.py](https://github.com/MarianoSevilla/fiscal-cripto-/blob/bb84e75a876f936a94b80b1c6dc064e39b46afeb/fiscal_app_export/communications/routes.py) |
| Eliminar cuenta | Desactiva y vacía email real, nombre, NIF, Google ID y contraseña. No hay eliminación transversal en esa función de FIFO, errores con email, contactos, solicitudes, entregas, archivos o respaldos; quedan otros campos de cuenta. No es anonimización global demostrada. | `_anonymize_user` (3703), `delete_account` (3719) en app.py |
| Cookies y conexiones externas | Sesión y recordatorio de 30 días; OAuth si está habilitado; Turnstile en Contacto y comprobación backend condicionada a configuración. Fuentes Google en algunas páginas anteriores. No se realizó una captura de red de todas las páginas ni auditoría de todas las cookies de terceros. | Configuración 216–218, `_verify_turnstile` (3924), [security_config.py](https://github.com/MarianoSevilla/fiscal-cripto-/blob/bb84e75a876f936a94b80b1c6dc064e39b46afeb/fiscal_app_export/security_config.py), contacto.html y signup.html |

## Correcciones editoriales aplicadas a la preview

1. Mantener la eliminación del enlace del hero «Consultar mis derechos» y conservar el índice y la sección de derechos.
2. Usar solo «Xirivella (Valencia)» como localización autorizada. No se añade dirección particular completa ni NIF privado; no se confunde con el domicilio de Rafa.
3. Describir almacenamiento temporal y registros persistentes por separado, incluidos resultados monetarios y logs del 721.
4. No prometer que descargar, cerrar cuenta, archivar o caducar un enlace elimina todos los datos.
5. Exponer diagnóstico automático sin atribuirlo a una autorización de envío posterior del CSV completo.
6. Describir las solicitudes de recursos y su condición actual de comunicaciones sin afirmar que el consentimiento esté correctamente separado o que el UID no se recoja.
7. Diferenciar solicitud de asesoramiento activa, documentación entregada a Rafa, archivos históricos potenciales y nuevas cargas/pagos suspendidos.
8. Distinguir correos transaccionales, capacidad técnica de campañas y declaración del titular de que actualmente no envía campañas. No inferir envíos a partir de tablas o código.
9. Explicar que las estadísticas actuales no son enteramente anónimas.
10. No afirmar una comprobación técnica de mayoría de edad que el registro no aplica.

## Hallazgos priorizados: no se corrigen funcionalidades en esta entrega

| Prioridad | Hallazgo / causa raíz | Acción separada recomendada |
|---|---|---|
| P1 | Política de producción describe memoria exclusiva, ausencia de resultados guardados y borrado total que el código no acredita. | Sustituir afirmaciones por la descripción verificada, con revisión editorial final. |
| P1 | No hay calendario transversal acreditado de conservación/supresión; la descarga y la eliminación de cuenta son operaciones parciales. | Adoptar plazos por categoría y procedimiento completo, incluidos archivos huérfanos, relacionados, correo y respaldos. La auditoría de código no permite inventar esos plazos. |
| P1 | Recurso condicionado a marketing; selección de campañas basada en no haber solicitado baja, sin requisito de prueba de opt-in. | Separar entrega y marketing, resolver legitimación y conservar prueba por origen antes de lanzar campañas. Revisar envíos individuales. |
| P1 | Resultados monetarios y diagnóstico persistentes contradicen el objetivo futuro de no retener información fiscal. | Preparar cambio independiente con migración/reconciliación de métricas y propuesta explícita para datos existentes, sin borrado en esta entrega. |
| P2 | Direcciones/roles profesionales y garantías internacionales no se desprenden del código. | Verificación documental con titular/profesional/proveedores. No dar una certificación por el mero cambio de texto. |
| P2 | Registro enlaza a `/legal/privacidad` y `/legal/terminos`, mientras las rutas revisadas son `/privacidad` y `/terminos`. No hay comprobación técnica de edad. | Corregir primera capa y coherencia con condiciones en un cambio acotado. |
| P2 | Logs de errores, cabeceras y valoración 721 pueden contener información del usuario; los comentarios «sin PII» no prueban anonimato. | Minimizar contenido y definir acceso y conservación; revisar excepciones y logs con datos sintéticos. |

Describir una condición existente no la convierte en lícita. La política puede actualizarse para ser veraz sin esperar a implantar todas las funciones futuras, pero la transparencia no sustituye la base jurídica, los plazos de conservación, los contratos ni la atención efectiva de derechos.

## Bases jurídicas y límites de esta auditoría

El cálculo solicitado y la gestión necesaria de la cuenta encajan, como propuesta editorial, en la ejecución del servicio; la solicitud de asesoramiento puede dar lugar a medidas precontractuales a petición del interesado. No se da por justificada automáticamente la conservación indefinida de resultados o su segmentación bajo esa misma base.

Los intereses legítimos para seguridad, estadísticas, segmentación y determinados contactos requieren concretar finalidad, necesidad y ponderación. El código muestra finalidad técnica, pero no demuestra por sí solo una ponderación jurídica. El formulario de recurso registra una casilla; eso no prueba libertad de elección cuando bloquea la entrega por no aceptar marketing. No se aplica la etiqueta genérica «consentimiento» a todas las cuentas ni a la simple lectura de la política.

Rafa presta y cobra directamente su servicio según la declaración del titular y Mariano recibe una comisión. Eso no atribuye al profesional toda la responsabilidad de los tratamientos de la plataforma. Los contratos y la decisión efectiva sobre fines/medios determinan los papeles para cada flujo; su verificación documental queda pendiente.

No se infiere la región de alojamiento, un mecanismo concreto de transferencia ni la eliminación de respaldos desde el código. Las condiciones públicas de proveedores son documentación de referencia, no prueba del contrato/configuración específicos de esta cuenta.

## Cambios y validación

Se actualizan únicamente los dos HTML de Privacidad en la rama de preview y documentación de diseño/auditoría. Se mantienen CSS, scripts, controles de seguridad, lógica FIFO/721, estadísticas y datos. La preview conserva `noindex,nofollow`, sesión de visitante local y ausencia de formularios o llamadas a producción.

Comprobaciones editoriales: once secciones, IDs y enlaces internos coherentes, igualdad del contenido entre variante estática y visor, enlace eliminado ausente y ausencia de identificación privada. Se mantiene la batería de 27 escenarios responsive en 13 anchos y las regresiones existentes de CI. Los resultados de esta revisión deben consultarse en la ejecución asociada al nuevo commit, sin reutilizar el estado verde de un commit anterior.

No se han creado cuentas ni enviado consultas, archivos, emails, campañas o pagos. No se han leído registros reales para determinar si existen datos heredados; esas afirmaciones se mantienen condicionales.

## Actualización continua

Cada cambio que recoja, escriba, comunique, registre o elimine datos debe revisar: datos/finalidad/base; tablas/temporales/logs; destinatarios y transferencias; conservación/supresión; primera capa y derechos. El cambio funcional y su explicación en Privacidad deben entrar en la misma entrega cuando proceda. No anunciar una función de borrado antes de que esté implantada y probada.

## Fuentes primarias consultadas

- [RGPD: artículos 5, 6, 7, 12–14, 17, 21–22, 28 y 44–49](https://www.boe.es/buscar/doc.php?id=DOUE-L-2016-80807).
- [LOPDGDD](https://www.boe.es/buscar/act.php?id=BOE-A-2018-16673).
- [LSSI: identificación, comunicaciones y cookies](https://www.boe.es/buscar/act.php?id=BOE-A-2002-13758).
- [Railway, DPA](https://railway.com/legal/dpa).
- [Resend, DPA](https://resend.com/legal/dpa).

Este informe es técnico/editorial y delimita lo demostrado por el código. Las decisiones de cumplimiento no acreditadas siguen abiertas; no requieren publicar la dirección privada del titular en el informe de auditoría.


## Integración de producción autorizada — 18 de octubre de 2026

Tras revisar la versión que describe el comportamiento actual, el titular autoriza su publicación. La entrega limpia parte de main y sustituye `static/privacidad.html`, añade `static/legal_apple.css` e incorpora QA de la ruta local `/privacidad`. Se conservan canonical e indexación de producción. No se incluyen el visor Netlify, su fixture de sesión ni la variante `_apple`.

Los 25 escenarios de producción sustituyen a los 27 de preview: se retiran únicamente las dos comprobaciones específicas del visor autocontenido. Se mantienen trece anchos, roles sintéticos, teclado, no-JS, texto al 200 %, sesión demorada e impresión. El contenido aprobado se transfiere sin cambios, salvo el metadato robots necesario para producción. Los estados efectivos de CI y despliegue deben verificarse en la PR de integración.

La integración no implanta la futura eliminación de resultados ni altera datos, almacenamiento, estadísticas, seguridad, pagos o cálculo. Los límites de la auditoría y las decisiones documentales pendientes descritos arriba siguen vigentes.
