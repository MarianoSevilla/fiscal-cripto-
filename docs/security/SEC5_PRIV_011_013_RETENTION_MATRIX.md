# SEC5-PRIV-011/012/013 — Inventario y decisiones de conservación

**Estado:** propuesta técnica para revisión, **no política de retención aprobada**.  
**Continuación:** [borrador de criterios para aprobación, sin purgas ni cambios de producción](SEC5_PRIV_011_013_DECISION_PROPOSAL.md). La propuesta distingue plazos internos sugeridos de obligaciones legales acreditadas; no sustituye esta matriz de inventario.  
**Fecha de corte:** 28/10/2026.  
**Repositorio base:** `MarianoSevilla/fiscal-cripto-`, `main@2b360475f2ec2bb9c7a2e032a6db8efc57161d66`.  
**Fuentes del código:** `fiscal_app_export/models.py`, `app.py::_anonymize_user`, `static/privacidad.html#conservacion`, `communications/`, `fifo_pdf_lifecycle.py`.  
**Alcance de la comprobación:** modelo ORM (17 tablas), comportamiento de la función de eliminación y texto publicado. **No** auditoría de todas las tablas físicas, copias de seguridad o datos de producción.

## 1. Conclusión sobre «Eliminar mi cuenta»

`POST /api/delete-account` exige una contraseña válida o una confirmación OAuth; luego llama a `_anonymize_user`, hace `logout_user()` y contesta «Cuenta eliminada correctamente.».

La función **desactiva y desidentifica parcialmente** la fila de `users`, **no** efectúa una supresión global:
- Email sustituido por `deleted_<id>@deleted`, `password_hash`, `google_id`, nombre, NIF y marca de email verificado vaciados; `is_active=False`.
- **Corrección segura propuesta en esta PR:** además vaciar `comms_unsubscribe_token`, `password_reset_token_hash`, `password_reset_expires_at` y `last_login`, sin tocar expedientes o identidades ajenas.
- Siguen existiendo `users.id`, `created_at`, `role`, `plan`, `comms_opted_out` y referencias `user_id`. Es **seudonimización/desidentificación parcial**, no anonimato irreversible.
- Las tablas vinculadas conservan sus datos; algunas duplican el email, nombres o datos de pago. Las solicitudes de contacto o recursos pueden contener datos del mismo interesado **sin** clave foránea a `users`.
- Se desconoce aquí el estado de otras copias: archivos de asesoramiento, emails enviados, Resend, Stripe, Railway, backups, registros de infraestructura y terceros.

El mensaje de la página `/privacidad#conservacion` ya advierte que la eliminación no borra automáticamente todas las filas relacionadas. No cambiar su texto para prometer borrado global.

## 2. Matriz de las 17 tablas del modelo ORM

**Lectura:** «Actual» es lo que hace el código al eliminar una cuenta. «Acordar» es una decisión pendiente antes de programar una limpieza. No se fijan plazos legales hipotéticos.

| Tabla ORM | Datos/vínculo relevante | Actual tras eliminar cuenta | Acordar: criterio y tratamiento |
|---|---|---|---|
| `users` | Email, nombre, NIF, identidad Google, hashes, tokens; ID referenciado | Se desactiva, se sustituyen identificadores principales; esta PR borra además tokens y último acceso; permanece ID y metadatos | Si hay necesidad de conservar la fila de referencia, plazo de seudónimo; límites de acceso y supresión final |
| `fifo_reports` | `user_id`, exchange, ejercicios, tiempos, ganancias/pérdidas, estado del cálculo | Permanece con `user_id`; PDF no está en esta tabla | Finalidad de analítica/soporte, plazo desde descarga/fallo y anonimización real de datos agregados |
| `processing_errors` | `user_id`, **email directo**, nombre CSV, `traceback_short`, `csv_context`, fingerprint | Permanece, incluida copia de email y contexto | Plazo de resolución y revisión; minimización de datos diagnósticos (SEC5-PRIV-005/008/009) y borrado/seudónimo condicionado |
| `incidents` | Fingerprint, título, notas internas, errores agregados | Permanece; sin FK a usuario; notas pueden contener referencias | Plazo desde cierre y revisión de texto libre; evitar vinculación indirecta |
| `contactos` | Nombre, email, mensaje, IP, user agent; sin `user_id` | Permanece por separado; archivar no es borrar | Plazo desde fin de consulta, qué conservar para reclamaciones y cómo localizar por email |
| `fiscal_advisory_requests` | `user_id` opcional, nombre/email/teléfono, NIF y domicilio de facturación, expediente, presupuesto, Stripe/PayPal históricos, IP/UA | Permanece íntegra, incluidos datos copiados | Separar expedientes sin pago, prestados, cobrados y reembolsados; obligaciones contables/fiscales y acceso restringido |
| `s01_stripe_checkout_attempts` | FK a asesoramiento; intento, importe, claves idempotentes e IDs Stripe | Permanece | Integridad contable, conciliación y retención vinculada al expediente; no cascadas |
| `s01_stripe_event_receipts` | FK a intento, ID/tipo de evento Stripe | Permanece | Deduplificación y prueba de pagos; plazo y acceso restringido |
| `s01_stripe_notification_outbox` | FK a intento; estado y evidencia de notificación | Permanece | Trazabilidad de notificaciones, retención vinculada a pago |
| `fiscal_advisory_files` | FK a solicitud y a usuario, nombre, ruta, tipo y tamaño | Permanece la fila; **no se ha acreditado limpieza del fichero físico** | Inventariar soporte/ruta real antes de limpieza segura, preservar expedientes exigibles |
| `fiscal_advisory_status_history` | FK a solicitud y `changed_by`; notas y cambios de estado | Permanece | Historial necesario para servicio/reclamaciones y depuración de notas personales |
| `advisory_internal_notes` | FK a solicitud, `author_id`, nombre del autor copiado, texto libre | Permanece | Limitar acceso, plazo y supresión del texto superfluo |
| `advisory_audit_log` | `request_id` (sin FK), `admin_id`, detalle libre y acciones | Permanece | Protección de evidencia y restricción de uso; no borrar en cascada |
| `communication_campaigns` | Cuerpo, destinatario individual `individual_email`, creador e incidencia vinculada | Permanece, incluso email individual | Distinguir soporte de marketing; plazo por justificación y tratamiento de borradores |
| `communication_deliveries` | `user_id` opcional, **email copiado**, estado/proveedor/error | Permanece aunque el email de `users` cambie | Evidencia mínima de oposición/entrega, plazo y minimización de diagnósticos de proveedor |
| `resources` | Catálogo de contenido, ubicación de almacenamiento | Permanece; no es fila personal por defecto | Ciclo editorial independiente; revisar solo campos libres que puedan incorporar datos |
| `resource_requests` | **Nombre/email**, UID de exchange, Telegram, IP, notas y `marketing_consent`, sin FK a usuario | Permanece por separado; no afectada por eliminar cuenta | Separar entrega del recurso, consentimiento y afiliación; plazos y prueba del consentimiento |

**Observación de alcance:** las 17 tablas declaradas en el ORM se comparan con esta matriz mediante una prueba de regresión. Si se incorporan nuevas migraciones, comparar también con el esquema PostgreSQL real antes de actualizar la política.

## 3. Datos fuera de estas tablas

| Medio | Comportamiento conocido | Decisión pendiente |
|---|---|---|
| CSV/Excel cargados para FIFO | Limpieza temporal best-effort tras proceso, sin promesa absoluta ante fallo | Garantía operativa, logs, fallos y ubicación temporal |
| PDF FIFO | Entrega con token temporal de cinco minutos y purga best-effort | Verificación del volumen/respaldos y de fallos del sistema de archivos |
| Documentos de asesoramiento | La BD contiene `file_path`; la eliminación de cuenta no borra ficheros | Inventario real por proveedor, responsable de custodia y ciclo de vida |
| Resend y correos de soporte | Proveedor y bandejas pueden mantener copias fuera de PostgreSQL | Contrato/configuración, eliminación y conservación por cada finalidad |
| Stripe | Mantiene datos propios del pago; relaciones en `s01_*` y expedientes | Reglas fiscales/contables por tipo de operación, sin borrar evidencia válida |
| Railway/PostgreSQL/logs/backups | Ciclos del proveedor no acreditados con esta revisión de código | Verificar configuración, restauraciones, caducidad y borrado seguro |

## 4. Decisiones de producto y privacidad **sin cerrar**

1. **Cuenta desactivada:** conservar ID técnico solo durante la vida justificable de las referencias; prohibir reactivación implícita y uso comercial. Eliminar tokens como intervención segura inmediata.
2. **Informes y errores FIFO:** definir momento inicial, destinatario, finalidad y plazo. La capacidad de medir uso de producto no legitima conservar datos personales indefinidamente.
3. **Consultas y solicitudes de recursos:** inventariar registros mediante email normalizado (con cautela ante coincidencias y errores), no confiar solo en `user_id`; separar comunicaciones de servicio de marketing.
4. **Asesoramiento, pagos y auditoría:** decisión documentada según estado económico, facturación, obligaciones concretas y defensa de reclamaciones. No iniciar purga automática ni romper FKs por una eliminación de cuenta.
5. **Bloqueo y acceso:** determinar cómo impedir consulta/uso ordinario de datos que deban permanecer bloqueados y permitir solo acceso autorizado para fines legales. Un mero estado `archived`/`resolved` no demuestra bloqueo.
6. **Copias/proveedores:** verificar políticas reales, plazos, segregación y procedimiento de solicitudes; no afirmar plazos externos no comprobados.
7. **Transparencia:** una vez acordadas las decisiones, actualizar `/privacidad#conservacion` y el mensaje de eliminación de cuenta con el alcance verificable, no antes.

Cada fila/categoría precisa una decisión con **finalidad, base aplicable, evento inicial, plazo, destino (eliminar/anonimizar/bloquear), responsable y prueba de ejecución**. Solo después diseñar migración o mecanismo de supresión idempotente y pruebas aisladas.

## 5. Criterio jurídico comprobado (no plazo inventado)

- El artículo 5 RGPD recoge la limitación del plazo de conservación y la minimización; fuente AEPD: https://www.aepd.es/preguntas-frecuentes/2-tus-obligaciones-como-responsable-del-tratamiento/4-los-principios-del-tratamiento/FAQ-0207-que-principios-debo-cumplir
- El derecho de supresión tiene excepciones cuando concurren obligaciones legales o defensa de reclamaciones; fuente AEPD: https://www.aepd.es/derechos-y-deberes/conoce-tus-derechos/derecho-de-supresion-al-olvido
- Cuando corresponde el bloqueo, el artículo 32 LOPDGDD exige impedir tratamiento/visualización ordinarios, reservando acceso para los supuestos legales; fuente oficial: https://www.boe.es/eli/es/lo/2018/12/05/3/

**Esto no acredita automáticamente** ningún plazo de retención específico para una tabla, factura, comunicación o copia. Requiere examinar la finalidad y obligaciones efectivamente aplicables.

## 6. Riesgos, aceptación y límites de la PR

- **Corrección ejecutable:** eliminar en `users` solo tokens de recuperación/desuscripción y último acceso una vez confirmada la identidad para eliminar cuenta.
- **Prueba sintética HTTP:** contraseña correcta y OAuth siguen desactivando; las credenciales se limpian; los registros de FIFO y diagnóstico relacionados **no** se borran por accidente.
- **Regresión de inventario:** toda nueva tabla declarada en el ORM debe reflejarse en esta matriz.
- **No se modifica:** cascadas, FKs, políticas de backup, borrado físico, facturas, pagos, proveedores, almacenamiento de expedientes, UI de cuenta ni política publicada.
- **Riesgo residual importante:** filas externas todavía contienen emails/PII y `user_id` pseudónimo; el flujo no representa una supresión exhaustiva de datos personales.
- **Cierre de SEC5-PRIV-011/012/013:** no declarar «supresión global resuelta» hasta aprobar la política por categorías e implementar sus medidas, con verificación operacional posterior.
