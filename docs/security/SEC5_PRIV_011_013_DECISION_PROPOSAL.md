# SEC5-PRIV-011/012/013 — Propuesta de decisiones de conservación y supresión

**Estado: BORRADOR PARA DECISIÓN DEL RESPONSABLE. No aprobado, no aplicado en producción.**  
**Corte técnico-jurídico:** 28 de octubre de 2026. Base `main@c95b91dadf28583d8167850ba3fcaae8509d6009`.  
**Ámbito:** los 17 modelos ORM inventariados en `SEC5_PRIV_011_013_RETENTION_MATRIX.md`, archivos locales, Gmail/Resend, pagos y respaldos. Sin inspección de datos personales reales ni configuración de retención de los proveedores.

## 1. Conclusión y límites

- `POST /api/delete-account` confirma identidad, desactiva la cuenta y limpia los principales identificadores, contraseñas, tokens y último acceso. Mantiene un registro `users` de referencia y **no elimina ni bloquea** automáticamente registros vinculados o correos que duplican la identidad. No afirmar "borrado integral".
- `fifo_reports` contiene importes (`resultado_neto`, `ganancias_brutas`, `perdidas_brutas`), año y referencia `user_id`. No es telemetría anónima. `processing_errors` puede contener `email`, `csv_context`, trazas y nombre del fichero, y carece de purga general. PR #154 minimiza nuevos diagnósticos; no elimina históricos.
- Las solicitudes `contactos` y `resource_requests` tienen email propio **sin FK** al usuario. Desidentificar `users.email` no las alcanza. También existen copias de email en asesoramiento y entregas de comunicaciones.
- Los CSV/Excel originales y PDF de cálculo tienen limpieza temporal **best-effort**; el PDF descargable caduca a los cinco minutos y existe purga periódica en proceso, pero no evidencia de destrucción instantánea ante caídas. El envío consentido de diagnóstico a Gmail/Resend posee su propio ciclo.
- **No se propone ninguna eliminación de expedientes, pagos, documentación fiscal, copias de seguridad o datos de terceros sin justificar sus obligaciones y aprobar el tratamiento.**

## 2. Marco normativo comprobado (no sustituye dictamen por caso)

1. RGPD artículos 5.1(c/e), 6 y 17: minimizar y limitar conservación; la supresión admite excepciones por obligaciones legales y defensa de reclamaciones. [Reglamento (UE) 2016/679](https://eur-lex.europa.eu/legal-content/ES/TXT/?uri=CELEX:32016R0679); [AEPD, derecho de supresión](https://www.aepd.es/preguntas-frecuentes/1-tus-derechos/2-tus-derechos-de-proteccion-de-datos/FAQ-0111-que-es-el-derecho-de-supresion-derecho-al-olvido).
2. Artículo 32 LOPDGDD: cuando proceda el bloqueo, exige **impedir uso y visualización ordinarios**, conservar solo para las finalidades legales indicadas y destruir tras la prescripción. Una marca `archived` o `resolved` **no demuestra bloqueo**. [BOE, LO 3/2018, art. 32](https://www.boe.es/eli/es/lo/2018/12/05/3/).
3. Artículo 30 del Código de Comercio: conservación de seis años de libros y justificantes **de los empresarios a los que resulte aplicable**, desde el último asiento y con salvedades. No justifica conservar seis años todos los CSV, informes o correos. [BOE, Código de Comercio](https://www.boe.es/buscar/act.php?id=BOE-A-1885-6627).
4. Artículos 66, 66 bis, 67 y 68 LGT: la prescripción tributaria ordinaria de cuatro años tiene inicio, interrupciones y reglas distintas de ciertas comprobaciones; **no es una autorización de retención universal de cuatro años**. [BOE, Ley 58/2003](https://www.boe.es/buscar/act.php?id=BOE-A-2003-23186).
5. Solicitudes de derechos: tramitar con diligencia; plazo ordinario de respuesta de un mes, con las prórrogas previstas en el RGPD. [AEPD, derechos](https://www.aepd.es/derechos-y-deberes/conoce-tus-derechos/derecho-de-supresion-al-olvido).

Las duraciones **30/90/180 días** que aparecen abajo son **propuestas de política interna**, NO mínimos ni máximos legales acreditados. Solo se convertirán en reglas cuando el responsable apruebe su finalidad, punto de partida, excepciones y ejecución.

## 3. Propuesta por grupos y tabla

| Tabla ORM | Finalidad y punto de partida | Tratamiento propuesto para decisión (NO aplicado) | Protección / condición |
|---|---|---|---|
| `users` | Cuenta activa; inicio: solicitud de eliminación validada | Desactivar y suprimir credenciales e identificadores inmediatamente (ya implementado parcialmente); mantener ID técnico **solo mientras lo exijan referencias justificadas** y destruir cuando sea posible | No permitir reactivación, campañas ni acceso normal a cuenta desactivada; revisar rol/plan remanentes y vínculos |
| `fifo_reports` | Historial funcional y métricas, desde generación/descarga | **Propuesta: 90 días** de registros individualizados para soporte; después desidentificar realmente las métricas necesarias o suprimir; en eliminación de cuenta evaluar adelanto salvo expediente/reclamación | Ganancias/pérdidas y `user_id` son identificables; métricas agregadas solo si no permiten reidentificar |
| `processing_errors` | Diagnóstico, desde resolución o última incidencia | **Propuesta: 30 días tras resolver y límite ordinario de 90 días desde el evento** para datos personales/contexto; incidencias abiertas requieren revisión documentada, no conservación ilimitada | Priorizar borrado de email, `csv_context`, trazas y filenames; conservar huella técnica solo tras comprobar que no identifica |
| `incidents` | Agrupación técnica, desde cierre de incidencia | Mantener huella y contadores no personales para regresión; revisar/expurgar notas libres con identidad | Separar incidencias abiertas de cerradas; no asumir que `notes` es anónimo |
| `contactos` | Atender consulta, desde respuesta final/archivo | **Propuesta: 180 días tras cierre** para consultas ordinarias; fuera de ese plazo suprimir datos de contacto salvo reclamación/obligación concreta | No equivale a contrato contable; controlar IP, UA y texto libre |
| `fiscal_advisory_requests` | Solicitud, presupuesto y expediente, desde cierre/último hecho económico | Sin pago ni prestación: propuesta de **180 días tras cierre**; con prestación, cargo, reembolso o conflicto: retener exclusivamente lo justificable por obligación/defensa, sujeto a clasificación | Separar expediente comercial de evidencia contable/fiscal; resolver rol de Rafa y cadena de custodia |
| `s01_stripe_checkout_attempts` | Estado de cobro e idempotencia, desde liquidación/cierre | Conservar mínimo necesario para conciliación, disputas y obligaciones que apliquen; no purgar por plazo genérico | Mantener consistencia con solicitud, Stripe y devolución; estados inciertos no se eliminan |
| `s01_stripe_event_receipts` | Deduplificación de webhook y evidencia, desde recepción | Igual que intentos vinculados, condicionados a comprobación fiscal/contable | No romper controles anti-duplicado o evidencia de cobro |
| `s01_stripe_notification_outbox` | Evidencia de comunicación de pago, desde envío/cierre | Mantener metadatos imprescindibles de estado, no contenido adicional innecesario; revisión junto al cobro | Nunca borrar evidencia activa en operaciones inciertas |
| `fiscal_advisory_files` | Adjuntos del expediente, desde cierre verificado | Sin pago/servicio: revisar supresión temprana; con prestación o requerimiento: custodia según necesidad comprobada | **No ejecutar** sin inventariar fichero físico, rutas, copias, custodio y estado de expediente |
| `fiscal_advisory_status_history` | Trazabilidad del expediente, desde cierre | Mantener eventos necesarios mientras subsista causa; minimizar notas personales libres | Integridad de auditoría, rol y acceso restringido |
| `advisory_internal_notes` | Gestión profesional, desde cierre | Eliminar/anular texto no necesario cuando cierre y no haya justificación posterior | Posibles NIF, teléfonos y relatos personales; tratamiento por caso |
| `advisory_audit_log` | Evidencia de acciones, desde último evento | Preservar evidencia pertinente durante obligaciones/disputas; limitar detalle textual | Un borrado masivo puede destruir trazabilidad necesaria |
| `communication_campaigns` | Mensajes, segmentación y consentimiento, desde fin de campaña | **Propuesta: 90 días** para borradores/error técnico sin necesidad activa; conservar prueba mínima de consentimiento/oposición durante justificación | `individual_email` puede identificar incluso sin `users`; no reutilizar para marketing |
| `communication_deliveries` | Historial técnico de entrega, desde intento | **Propuesta: 90 días** para diagnóstico de entrega; después separar evidencia mínima necesaria de bajas/consentimiento y borrar email/errores no pertinentes | Respetar bloqueos de marketing; no tratar la baja como señal que pueda borrarse sin evaluación |
| `resources` | Catálogo editorial, desde despublicación | Sin purga relacionada con eliminación de cuenta salvo datos personales insertados en campos libres | Catálogo no es por defecto dato del solicitante |
| `resource_requests` | Entrega y validación de recurso, desde resultado final | **Propuesta: 90 días tras envío/rechazo** para UID, Telegram, IP y datos de tramitación; preservar solo prueba mínima del consentimiento u oposición si resulta necesaria | Tiene `email` propio sin `user_id`; localizar registros por identidad verificada, evitar borrar datos de homónimos |

**Los 17 tratamientos anteriores están pendientes de aprobación.** Los relojes son orientaciones sobre el **uso ordinario** y la posterior supresión/bloqueo si procede: no significan destrucción automática al día N ni sustituyen plazos específicos de prescripción.

## 4. Fuera de PostgreSQL

| Soporte | Estado técnico conocido | Decisión o prueba necesaria |
|---|---|---|
| CSV/Excel para FIFO | Temporales liberados al terminar cuando es posible; no se afirma borrado físico infalible | Verificar ubicaciones, permisos, errores de proceso y no inclusión en backups persistentes |
| PDF FIFO | Token 5 min, lectura de un uso, purga local periódica best-effort | Mantener política actual; verificar únicamente eficacia operativa y copias cuando corresponda |
| CSV diagnóstico voluntario | Recepción Gmail verificada con CSV ficticio el 28/10/2026; interruptor público cerrado tras prueba | Mantener máximo operativo acordado **30 días en Gmail** y borrado anterior al resolver; la copia Resend tiene ciclo propio. No suponer eliminación de Gmail/Resend por un único borrado |
| Emails de soporte, contacto, campañas | Gmail y Resend mantienen datos fuera de DB | Política por asunto/finalidad, control de acceso, revisión de plazos del proveedor y retirada de adjuntos |
| Stripe | Evidencia financiera en proveedor y tablas `s01_*` | Definir responsable, sujetos, transacciones reales, conservación documental y conciliación; no asumir que todo dato Stripe puede purgarse |
| Documentos de Rafa | Rutas y entregas pueden residir en otro custodio/proveedor | Definir responsabilidad y datos bajo control propio; no prometer borrado sobre custodia ajena |
| Railway, logs y backups | Existe infraestructura productiva; no se han acreditado aquí sus tiempos de retención | Comprobar ciclos reales de backup, acceso/restauración, eliminación y posible propagación de supresiones |

## 5. Mecanismo técnico futuro (propuesta, sin ejecución)

1. **Clasificación por finalidad y retención** con estado del expediente/cobro: `operativo`, `candidato_a_suprimir`, `bloqueo_justificado`, `suprimido`. No basta un `archived=True` visible al usuario.
2. **Solicitud de derecho** con identidad acreditada y registro mínimo de recepción, análisis, decisión, base, comunicación y ejecución. Localizar relaciones por `user_id` y duplicados de email **antes** de sustituir el identificador original; referencias ambiguas se revisan manualmente.
3. **Bloqueo real**, si procede: impedir consultas ordinarias, búsquedas internas, exportación y campañas; acceso excepcional controlado, auditado y limitado para las finalidades permitidas. En ausencia de mecanismo válido, no afirmar "bloqueado".
4. **Supresión idempotente y segura**, solo tras aprobación: restricciones FK, anexos en disco, tokens, referencias de pago, emails y respaldos; estados parciales recuperables, exclusión de expedientes sujetos a obligación.
5. **Pruebas negativas en SQLite y PostgreSQL desechables**: no borrar otros usuarios, no romper relaciones contables, no exponer datos bloqueados a usuario/operador ordinario, repetición segura, falla de almacenamiento, reintentos y criterios de edad. Después auditar comportamiento real **sin leer ni modificar datos ajenos**.
6. **Comunicación pública** en `/privacidad#conservacion` y cuenta solo después de aprobación y pruebas. El texto actual refleja prudentemente que la eliminación de cuenta no borra todos los registros.

## 6. Decisiones solicitadas y puertas de seguridad

**A. Política orientativa de datos técnicos (requiere aprobación):** 90 días para registros individualizados de FIFO; 30 días tras resolución, máximo ordinario 90 días para errores; 180 días tras cierre para consultas; 90 días tras entrega para recursos; siempre sujeto a revisión de justificación y excepciones.

**B. Expedientes económicos (requiere revisión de rol y obligaciones):** distinguir solicitud no pagada, servicio prestado, facturación y disputa. Aplicar plazos mercantiles/tributarios **solo a los documentos y responsables a los que correspondan** y considerar inicios/interrupciones reales, no una regla global de cuatro/seis años.

**C. Bloqueo y supresión (requiere diseño y pruebas):** clasificar qué registros exigen bloqueo legal, qué datos deben destruirse al terminar la finalidad y cómo demostrar restricciones de acceso. Ninguna nueva purga se autoriza mediante este documento.

**D. Proveedores y custodia (requiere verificación):** Railway/PostgreSQL, Gmail, Resend, Stripe, asesor fiscal, copias de seguridad y ficheros de expedientes; no se certifican políticas de terceros a partir del código.

### Criterio de cierre de la fase

La fase solo se considerará cerrada cuando: (1) el responsable apruebe criterios por finalidad y excepciones; (2) se documenten plazos/soportes externos con evidencia suficiente; (3) cualquier implementación de bloqueo/supresión se pruebe con datos sintéticos y autorización separada; (4) el contenido legal publicado coincida con capacidades verificadas. **Esta PR es solo un borrador de decisión**, sin cambios de Flask, PostgreSQL, Railway ni datos reales.
