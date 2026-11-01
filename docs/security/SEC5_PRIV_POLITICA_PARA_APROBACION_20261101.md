# SEC5-PRIV-011/012/013 · Política de conservación por finalidad — decisión del titular

**Estado: PROPUESTA PARA APROBACIÓN, NO APROBADA NI IMPLEMENTADA.**  
**Corte:** 01/11/2026. **Repositorio base:** `main@916d97c74df1657fe2f28cf7f2eb85ff0d52535f`.  
**Objetivo limitado:** convertir la matriz existente en decisiones concretas y proporcionadas, sin cambiar la analítica, sin diseñar nuevas funcionalidades y **sin purgar, bloquear, migrar o acceder a datos de producción**.

## 1. Decisión esencial de producto

marianosevilla.com **no es un archivo documental fiscal**. Gestiona las cuentas y los informes FIFO; conecta a la audiencia con el economista **Rafael Ramos**, quien, según declaración del titular, custodia los documentos de la asesoría. El portal **sí** conserva registros persistentes identificables de cálculos, incidencias, solicitudes, recursos y operaciones administrativas/financieras en PostgreSQL. No afirmar que solo guarda cuentas y CSV temporales. Tampoco inferir que los documentos históricos de asesoramiento no existen: `fiscal_advisory_files` y una ruta de descarga protegida siguen presentes; la subida nueva está deshabilitada por defecto.

La capacidad de **estadísticas potentes, agregadas, sin seguimiento individual para analítica** se preserva. Su auditoría/mejora queda **expresamente aplazada por el titular**; este documento no reabre ese frente ni elimina registros analíticos. La minimización de importes fiscalmente identificables se planificará sin modificar el panel en esta fase.

### Clasificación de decisiones

- **O — Operación:** se mantiene mientras la finalidad legítima subsista (cuenta, soporte abierto, prestación, compra y acceso). Requiere base jurídica documentada y controles de acceso.
- **R — Revisión programada:** a los días indicados se examina si el dato sigue siendo necesario; **no es un plazo legal ni autoriza retención automática hasta ese día o borrado automático al alcanzarlo**. Si la finalidad termina antes, evaluar antes.
- **L — Retención legal/evidencia justificada:** separar solo los campos necesarios para deberes legales o defensa de reclamaciones; definir norma, inicio real, interrupciones y plazo. Cuando corresponda el art. 32 LOPDGDD, **bloqueo efectivo** con acceso excepcional controlado y posterior destrucción.
- **A — Agregado realmente anónimo:** conservar estadísticas únicamente después de evaluar irreversibilidad, tamaño de grupos y posible enlace indirecto. La seudonimización no excluye RGPD.
- **H — En espera de verificación:** no implantar supresión irreversible sin aclarar obligaciones, custodio, proveedor o estado de pago. No justifica uso ordinario indefinido.

## 2. Matriz de decisión propuesta: 17 tablas ORM

**Cómo leer la tabla:** en «revisión» se propone el **punto de decisión**, no un calendario de eliminación; «destino» establece qué decisión tomar si la finalidad cesa, condicionada al análisis de excepciones. Todas estas filas requieren ratificación del responsable antes de traducirse a código.

| Tabla ORM | Finalidad y base RGPD a confirmar | Disparador / revisión propuesta | Destino y condición esencial |
|---|---|---|---|
| `users` | **O:** acceso y cuentas; art. 6.1(b) cuando proceda; seguridad/prevención de abusos: valorar 6.1(f) | Mientras cuenta activa. Al solicitar baja, actuación inmediata de desactivación; cuentas inactivas: **revisión a los 24 meses** desde último acceso válido, **no baja automática** | Revocar sesiones/credenciales; suprimir identificadores sin finalidad; mantener ID solo mientras referencias justificadas lo requieran. La baja actual no limpia datos asociados; no prometer anonimización completa |
| `fifo_reports` | **O/A:** gestión del informe, descargas, soporte y métricas agregadas; valorar 6.1(b)/(f) por finalidad | Registros individuales: **revisión a 90 días** de generación o última descarga legítima (la fecha más reciente). Nuevas compras/derechos de descarga **H** hasta definir producto 2027 | Priorizar retirar `resultado_neto`, `ganancias_brutas`, `perdidas_brutas` y `user_id` cuando ya no sean necesarios individualmente; mantener solo agregación realmente anónima tras evaluación. No eliminar compras, derechos de uso, quejas o evidencia |
| `processing_errors` | **O:** diagnosticar, atender errores y prevenir regresiones; valorar 6.1(b)/(f) | **Revisión a 30 días desde `resolved_at`** y a **90 días desde `created_at`** si sigue abierta (escalado, no purga) | Primero minimizar `email`, `csv_context`, `traceback_short`, `csv_filename` históricos; no romper tickets abiertos ni soporte consentido. La huella técnica exige comprobación antes de llamarla anónima |
| `incidents` | **O/A:** causa raíz de incidencias y calidad | Al cierre `resolved_at`, **revisión a 90 días**; nuevas regresiones justificadas generan nueva evaluación | Conservar patrones técnicos no vinculables; reducir `notes` y títulos libres con identidad; incidencia activa o regresión pendiente conserva finalidad |
| `contactos` | **O:** responder consultas o solicitudes precontractuales; valorar 6.1(b)/(f), según asunto | Desde respuesta/cierre real; **revisión a 180 días**. `archived_at` solo si acredita cierre | Suprimir nombre, email, IP/UA y mensaje cuando no se justifiquen; separar prueba mínima de reclamación o incidencia en curso. Las filas **no tienen FK** a `users` |
| `fiscal_advisory_requests` | **O/L/H:** intermediación, presupuesto, entrega al profesional, pruebas de servicio y, cuando exista, evidencia de pago | Solicitud sin prestación ni cobro: **revisión a 180 días del cierre real**; presupuestos abiertos, pagos, reembolsos, obligaciones y controversias: **H/L** | Mantener solo estado/contrato/evidencia justificables; priorizar minimización de relato fiscal libre, NIF, direcciones e IP de aceptación. Determinar responsable, flujo con Rafael y quién factura/cobra. Nunca usar 4/6/10 años para toda la tabla |
| `s01_stripe_checkout_attempts` | **O/L:** idempotencia, conciliación, cobro y defensa | Desde liquidación/conciliación **acreditada** y ausencia de disputa; revisión separada técnica/contable | Conservar claves/relaciones imprescindibles; **H** si estado incierto; aplicación de deberes mercantiles/fiscales solo a justificantes afectados, no a todas las columnas |
| `s01_stripe_event_receipts` | **O/L:** deduplicación y comprobación de webhooks | Desde conciliación y fin de necesidad de reintento/evidencia; **sin borrado por edad genérica** | Minimizar solo con preservación de integridad y evidencia necesaria; **H** hasta identificar operación/obligación y proveedor |
| `s01_stripe_notification_outbox` | **O/L:** envíos de comprobantes/notificaciones y reintentos | Tras envío confirmado/supresión legítima y cierre financiero; **revisión técnica a 90 días** solo de fallos/datos accesorios | Nunca borrar `pending`, evidencias de pago ni clave de idempotencia imprescindible; retención ligada a transacción |
| `fiscal_advisory_files` | **H:** metadatos de posible archivo heredado (fila no prueba existencia del fichero) | Inventario **manual de ruta, soporte, custodio y expediente** antes de fijar plazo | No autorizar borrado de fila/fichero ni prometer ausencia de copias. Para nuevos documentos la custodia profesional corresponde a Rafael según titular; verificar históricos y acuerdo |
| `fiscal_advisory_status_history` | **O/L:** estados y trazabilidad de solicitud | Solicitud sin pago: revisar **180 días tras cierre**; con operación económica, mantener mientras evidencia necesaria | Minimizar `note` libre y vínculos personales solo cuando no perjudiquen reclamación o integridad |
| `advisory_internal_notes` | **O/H:** notas de gestión restringidas | **Revisión a 180 días** de cierre sin servicio/cobro; otros casos ligados a expediente | Suprimir información fiscal accesoria cuando no necesaria; evaluar nombres y texto; no conservar indefinidamente por comodidad administrativa |
| `advisory_audit_log` | **O/L:** traza de acciones sensibles | Desde último evento y cierre de relación/obligaciones; **revisión ligada al expediente**, no purga automática | Conservar evidencia necesaria, reducir `detail` libre; `request_id` sin FK exige revisión específica de integridad |
| `communication_campaigns` | **O/L:** borradores y gestión de envíos autorizados; art. 6.1(a) para marketing por consentimiento cuando proceda; excepciones LSSI caso a caso | Borradores no usados / campañas cerradas: **revisión a 90 días**. Envíos fallidos activos: H | Limpiar destinatario individual, texto libre y errores superfluos; no convertir registros históricos de consentimiento forzado en permiso comercial |
| `communication_deliveries` | **O/L:** entrega, incidencias y evidencia de baja | **Revisión a 90 días** del último intento cerrado; excepciones para reclamación y oposición | Suprimir trazas de entrega innecesarias, pero **preservar evidencia mínima de oposición/baja** para impedir nuevas comunicaciones improcedentes; distinguir prueba de consentimiento de log completo |
| `resources` | **O:** catálogo editorial | Desde despublicación: revisar solo material editorial o datos personales accidentales; **sin retención de usuario aplicable por defecto** | No borrar recursos por baja de un solicitante; `storage_key` es metadato y no acredita que exista bucket |
| `resource_requests` | **O/L:** solicitud, validación de entrega y posible prueba de consentimiento | Desde enviado/rechazado/retirado con cierre efectivo: **revisión a 90 días**; pendientes H | Suprimir UID de exchange, Telegram, IP y contacto innecesarios; conservar prueba mínima de consentimiento/oposición de manera separada y válida. Los `marketing_consent=True` **anteriores a PR #161 no prueban consentimiento libre** |

### Plazos aplicables fuera del reloj de revisión

1. **RGPD:** arts. 5.1(c/e), 6, 13 y 17. No establece «30/90/180 días» generales. El responsable documenta finalidad, legitimación y criterios de conservación; la supresión admite excepciones específicas. [Texto oficial](https://eur-lex.europa.eu/legal-content/ES/ALL/?uri=celex%3A32016R0679).
2. **LOPDGDD art. 32:** bloqueo en supresión/rectificación cuando corresponda; bloqueo exige imposibilitar tratamiento y visualización corrientes, acceso excepcional limitado, destrucción tras prescripción aplicable. **No** basta `is_active=False`, `archived` o `resolved`. [BOE](https://www.boe.es/buscar/act.php?id=BOE-A-2018-16673).
3. **Código de Comercio art. 30:** seis años para libros, correspondencia y justificantes concernientes al negocio de los empresarios sujetos, desde último asiento, con salvedades. **No** todos los CSV o `fifo_reports`. [BOE](https://www.boe.es/buscar/act.php?id=BOE-A-1885-6627).
4. **LGT arts. 66, 66 bis, 67 y 68:** cuatro años de prescripción tributaria ordinaria, con cómputos e interrupciones específicos y supuestos adicionales. **No** retención universal de cuatro años. [BOE](https://www.boe.es/buscar/act.php?id=BOE-A-2003-23186).
5. **Ley 10/2010 art. 2.1(m) y 25 (texto actualizado en 2026):** la actividad profesional de asesoramiento fiscal figura en los sujetos obligados; **diez años** para la documentación exigida por esa ley, con restricción específica de acceso a los cinco años. Corresponde examinar su aplicación a **Rafael y, solo si los hechos lo justifican, a Mariano**; no extenderla a la base FIFO por mera intermediación. [BOE](https://www.boe.es/buscar/act.php?id=BOE-A-2010-6737).
6. **LSSI art. 21:** la publicidad electrónica requiere solicitud o autorización previa, salvo excepción definida para clientes previos y productos/servicios propios similares, con oposición sencilla y gratuita. El dato `marketing_consent` de formularios históricos forzosos **no equivale** a autorización libre. [BOE](https://www.boe.es/eli/es/l/2002/07/11/34/con).
7. **Derechos:** art. 12.3 RGPD, comunicación de respuesta normalmente en un mes desde recepción, ampliable en condiciones estrictas; el procedimiento ya está en `SEC5_PRIV_DERECHOS_SUPRESION_PROCEDIMIENTO.md`.

## 3. Datos y copias fuera de las 17 tablas

| Soporte | Criterio propuesto | Estado de evidencia |
|---|---|---|
| CSV/Excel FIFO de entrada | Uso temporal hasta terminar análisis; borrar archivos temporales en éxito/error, controlar residuos y fallos. **No** usar CSV para analítica ni conservar su historial por defecto | Código hace `os.unlink` best-effort; no acredita borrado infalible ante interrupción |
| PDF FIFO | Temporal con token de descarga cinco minutos y eliminación/limpieza periódica best-effort; la validez del enlace no demuestra borrado físico instantáneo | `fifo_pdf_lifecycle.py`: TTL 300 s y reaper; verificar logs/escenarios adversos antes de afirmar garantía absoluta |
| Diagnóstico CSV voluntario | Separado de cálculo; no enviar sin autorización explícita por evento. Buzón Gmail: máximo operativo ya comunicado de **30 días desde recepción o antes al resolver**, con borrado de Papelera según procedimiento; proveedor Resend por su propio ciclo | Gate público desactivado según evidencia previa; no activar para público hasta revisar proveedor y procedimiento |
| Otros correos Gmail/Resend | Separar contacto, soporte, comunicaciones y expedientes; revisar mensajes/adjuntos y políticas del proveedor; no equiparar bandeja o papelera con eliminación universal | Contratos, copias y políticas efectivas todavía por verificar |
| Stripe y facturación | Distinguir cuenta de cobro, operador económico, factura, soporte y disputas. Documentos económicos con deberes específicos, no purga genérica | Debe verificarse atribución del cobro e intermediación realmente realizada |
| Rafael / expediente profesional | Rafael custodia documentos de clientes según titular; acordar el traspaso de datos e información al interesado y reparto de roles | El portal conserva formulario y posibles metadatos históricos; relación contractual pendiente de documentar |
| Railway (PostgreSQL, logs, backups) | Inventariar región, DPA/encargos, accesos, backups, ciclos de restauración, ventanas de supresión y transferencias a terceros países. Un backup no se considera borrado por desactivar cuenta | Web y PG de producción online; región US previa constatada, contrato y garantías efectivas no acreditados todavía |
| Sistemas no inventariados | Identificar copias secundarias, históricos y otros canales de atención si aparecen en revisión | Prohibido afirmar exhaustividad basándose solo en modelos ORM |

## 4. Reglas para convertir la política en código (fase posterior, no autorizada)

1. **No hay purga automática por una cifra.** Exigir evento acreditado, finalidad extinguida, base legal, responsable, obligaciones, excepción, decisión motivada, destino y comprobación. Un cambio de vista a «archivado» o lectura de admin no altera fecha de cierre.
2. **Baja de cuenta ≠ supresión integral.** Antes de desidentificar, localizar referencias `user_id`, correos independientes, terceros y excepciones. En igualdad de nombres o emails ambiguos, parar para revisión; no afectar a otras personas.
3. **Bloqueo efectivo:** impedir acceso desde API, página y operación ordinaria, exportación y campañas; solo acceso excepcional legal limitado y registrado. Si el esquema no permite separar correctamente acceso y conservación, usar el mecanismo técnico legalmente admisible de forma explícita y comprobada.
4. **Derechos adquiridos:** no romper compras de informes, pagos idempotentes, solicitudes abiertas, reembolsos o derechos de descarga; la monetización FIFO 2027 requiere fijar primero el período de acceso pagado.
5. **Validar sin usuarios reales:** pruebas negativas multicuenta, relojes UTC, pagos pendientes, copias de email, ficheros, reintentos, aislación del bloqueo y defensa de reclamaciones en SQLite y PostgreSQL desechables. Una prueba de CI no acredita una eliminación en Gmail/Railway/Stripe.
6. **No ampliar estadísticas:** solo se define qué datos personales no deberían retenerse sin finalidad. La auditoría del panel queda aplazada y requerirá encargo propio.

## 5. Decisiones concretas reservadas para aprobación

**Propuesta recomendada — ratificar en bloque como criterios de diseño:**
- Cuenta activa = servicio; baja validada = desactivación inmediata; 24 meses de inactividad = revisión, nunca baja automática.
- FIFO individual = revisar a 90 días desde generación/última descarga, sin perjudicar compras o soporte; priorizar desidentificación de **importes fiscales personales** frente a métricas agregadas.
- Diagnóstico = revisar 30 días tras resolver y, si no resuelto, escalar a 90 días desde evento; incidentes cerrados 90 días.
- Consultas y solicitudes de asesoramiento **sin prestación/pago** = revisar a 180 días de cierre.
- Solicitudes de recursos, entregas de comunicaciones y borradores/campañas finalizados = revisar a 90 días de cierre.
- Evidencia económica y expedientes profesionales = conservar solo conforme a obligación/defensa **acreditada**, custodio y fechas verificadas; excluidos de borrado por criterio general.

**Aún no validable sin hechos externos o producto:**
1. Reparto responsable/encargado/independientes en la **intermediación**, el **cobro/facturación** y los **expedientes** de Rafael; aplicación concreta de AML si procede a la práctica del asesor.
2. Contratos DPA, transferencias internacionales y ciclo real de copias de **Railway, Gmail, Resend y Stripe**.
3. **Duración de derechos de acceso/descarga comprados** y obligaciones del futuro producto FIFO de pago.
4. Tratamiento de objetos/filas de `fiscal_advisory_files` que puedan permanecer de etapas anteriores.

**Autoridad y estados:** la respuesta «procedamos» del titular autoriza **preparar y comprobar esta propuesta**, no aprobar plazos finales, generar borrados o afectar a producción. Aprobación de criterios, implementación, cambios de permisos, fusión, despliegue y cualquier operación sobre datos reales requieren decisiones separadas. Hasta entonces se mantienen las protecciones existentes, los derechos de interesados y la obligación de evaluar cualquier solicitud real sin dilación.

## 6. Criterio de aceptación de esta entrega documental

- Inventario completo de **17/17** tablas ORM, sin atribuir anonimato por mera seudonimización.
- Una finalidad, propuesta de base jurídica, disparador de revisión, destino y excepción en cada tabla.
- Distinción explícita entre **revisión**, **retención legal**, **bloqueo** y **destrucción**.
- Expresión veraz sobre CSV/PDF temporales, registros persistentes y custodia de Rafael.
- Ningún cambio de cálculo fiscal, estadísticas, pagos, cuentas, comunicaciones, tablas, migraciones, ejecución de plazos, datos reales ni producción.
- El documento no modifica ni sustituye automáticamente la política publicada `/privacidad`; eso exige una intervención y autorización posterior.

**Fuentes técnicas:** `fiscal_app_export/models.py`, `app.py`, `fifo_pdf_lifecycle.py`, `error_tracking.py`, `static/privacidad.html`; `docs/security/SEC5_PRIV_011_013_RETENTION_MATRIX.md`, `SEC5_PRIV_011_013_DECISION_PROPOSAL.md`, `SEC5_PRIV_011_013_ACCEPTANCE_CONTRACT.md` y `SEC5_PRIV_DERECHOS_SUPRESION_PROCEDIMIENTO.md`.
