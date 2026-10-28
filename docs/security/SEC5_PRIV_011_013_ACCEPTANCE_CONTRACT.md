# SEC5-PRIV-011/012/013 — Contrato de aceptación para conservación y bloqueo

**Estado:** especificación de revisión; no aprobada para ejecutar. **Fecha:** 28/10/2026.
**Fuentes:** `SEC5_PRIV_011_013_RETENTION_MATRIX.md`, `SEC5_PRIV_011_013_DECISION_PROPOSAL.md` y `fiscal_app_export/models.py`.
**Alcance:** solo criterios verificables de diseño para las 17 tablas ORM. Ninguna migración, purga, despliegue, cambio de permisos ni acceso a datos reales.

## 1. Decisión de arquitectura mínima

Separar tres operaciones que no son equivalentes:
1. **Desactivar cuenta:** revocar acceso y credenciales; el flujo existente no supone supresión integral.
2. **Minimizar o suprimir:** eliminar datos sin finalidad vigente, tras comprobar relaciones, derechos de usuario y excepciones.
3. **Bloquear cuando corresponda jurídicamente:** excluir de consultas, búsqueda, soporte corriente, exportaciones y campañas; permitir solo acceso excepcional y auditado por la finalidad legal. No basta `archived`, `resolved` ni una bandera sin aislamiento real.

**No introducir un job automático ni cambios de esquema hasta demostrar las condiciones siguientes.** Los umbrales 30/90/180 días son *revisiones candidatas*, no fechas de borrado ni plazos impuestos por ley.

## 2. Decisiones por conjunto (cobertura de las 17 tablas)

| Tabla | Evento que debe acreditarse | Revisión / destino propuesto | Puerta de seguridad |
|---|---|---|---|
| `users` | Supresión de cuenta validada | Desactivar y revocar; evaluar referencias técnicas para supresión posterior | No confundir ID persistente con anonimato |
| `fifo_reports` | Generación o última descarga legítima | Revisar a 90 días; minimizar o suprimir datos individualizados si ya no necesarios | No perjudicar informes adquiridos, soporte ni reclamaciones; `user_id` e importes son personales |
| `processing_errors` | Resolución acreditada y fecha de evento | Revisar 30 días tras resolución; reevaluar a 90 días del evento | Nunca purgar incidencias abiertas; identificar históricos con `email`, `csv_context`, trazas, filename |
| `incidents` | Cierre real y última recurrencia | Revisar notas libres; conservar métricas no personales solo tras validación | `fingerprint` y texto pueden permitir vinculación |
| `contactos` | Respuesta final/cierre | Revisar a 180 días; suprimir cuando desaparezca finalidad salvo excepción | Identidad independiente sin FK, evitar coincidencias erróneas |
| `fiscal_advisory_requests` | Cierre, prestación y último hecho económico | Sin servicio ni cobro, revisión a 180 días; otras categorías según obligación aplicable | Pago, reclamación o presupuesto abierto excluyen purga automática |
| `s01_stripe_checkout_attempts` | Liquidación / cierre conciliado | Conservar evidencia imprescindible según finalidad aplicable | Estados inciertos, disputas e idempotencia protegidos |
| `s01_stripe_event_receipts` | Recepción y liquidación conciliada | Asociar conservación a transacción y deduplicación | No romper prueba de webhook o cobro |
| `s01_stripe_notification_outbox` | Envío o cierre de notificación y transacción | Minimizar según evidencia necesaria | No borrar notificaciones activas o con reintentos |
| `fiscal_advisory_files` | Cierre verificado y custodia identificada | Revisión manual de adjuntos, rutas y copias | Prohibido borrar filas sin verificar objeto físico, expediente y responsable |
| `fiscal_advisory_status_history` | Cierre del expediente | Retener eventos necesarios; minimizar texto accesorio | Preservar trazabilidad de cambios |
| `advisory_internal_notes` | Cierre y revisión de finalidad | Retirar notas libres innecesarias | Acceso restringido y posible información fiscal identificable |
| `advisory_audit_log` | Último evento y fin de obligaciones | Preservar evidencia relevante; minimizar texto | La relación por `request_id` no garantiza FK |
| `communication_campaigns` | Fin de campaña, borrador o incidencia | Revisar borradores y diagnósticos a 90 días | Separar soporte, marketing y evidencia de oposición |
| `communication_deliveries` | Último intento | Revisar detalle de entrega a 90 días | No borrar prueba mínima de baja o consentimiento sin análisis separado |
| `resources` | Despublicación de catálogo | Sin plazo personal general | Revisar únicamente campos editoriales con datos personales |
| `resource_requests` | Envío, rechazo o resolución | Revisar a 90 días; minimizar UID, Telegram, IP y datos de entrega | Email sin FK; conservar prueba mínima de consentimiento/oposición por separado |

## 3. Reglas obligatorias antes de implementar

- Cada finalidad requiere **responsable, base jurídica, disparador UTC, criterio de vencimiento, excepción, destino, evidencia y mecanismo de acceso**. Un simple acceso interno no reinicia la antigüedad.
- Consulta activa, ticket abierto, adquisición de informe, conflicto de pago, requerimiento, devolución o reclamación suspenden la ejecución irreversible hasta decisión motivada.
- Distinguir **métricas agregadas irreversiblemente anónimas** de datos seudonimizados vinculables; agregación por sí sola no demuestra anonimato.
- La resolución de una solicitud de derechos debe recorrer relaciones por `user_id` y datos copiados por email en tablas sin FK, antes de destruir identificadores de búsqueda; coincidencias ambiguas se escalan, nunca borrado por homonimia.
- Fuentes externas: Gmail, Resend, Stripe, Rafael Ramos, Railway, logs, backups y ficheros físicos requieren evidencia de custodia, acceso, retención y procedimiento de supresión o excepción. No atribuirles garantías no verificadas.
- El texto público no cambia hasta que el tratamiento real esté probado y autorizado.

## 4. Pruebas de aceptación antes de autorizar ejecución

1. **Cobertura:** inventario ORM y esquema PostgreSQL desechable concuerdan; las 17 tablas se clasifican y cualquier tabla nueva falla la regresión documental.
2. **Aislamiento:** eliminación solicitada por A jamás modifica filas, ficheros ni referencias de B; emails coincidentes/ambiguos exigen revisión.
3. **Bloqueo:** registros bloqueados no aparecen en vista de usuario, búsquedas internas corrientes, campañas, exportaciones ni tareas normales; solo acceso excepcional autorizado queda auditado.
4. **Integridad:** ningún proceso borra pagos no conciliados, solicitudes abiertas, información imprescindible para una descarga adquirida ni evidencia de disputas/reembolsos.
5. **Idempotencia:** reintentos tras fallo parcial de DB/disco/proveedor no duplican actuaciones ni destruyen evidencia; queda estado recuperable.
6. **Tiempo:** se prueban límites antes/en/después de la revisión y reapertura legítima de incidencia, con reloj UTC controlado; ningún umbral activa por sí solo borrado.
7. **Externos:** las acciones sobre fichero/correo/proveedor tienen verificación de resultado o excepción registrada; una limpieza local no se contabiliza como borrado universal.
8. **Derechos:** identidad comprobada, trazabilidad mínima de solicitud, decisión, excepciones y comunicación; resultados verificables sin retener más datos de los necesarios.
9. **Entornos:** SQLite y PostgreSQL sintéticos; sin contacto con clientes, credenciales reales ni base de producción.

## 5. Pendientes que impiden la activación

- Determinar roles contractuales y obligaciones sobre expedientes de asesoramiento, facturación, Stripe y documentos custodiados por Rafael Ramos.
- Verificar configuración efectiva y ciclos de Gmail/Resend, Railway, backups y registros.
- Resolver derecho y duración de descarga para informes FIFO de pago de 2027.
- Aprobar por finalidad la política definitiva, bases y excepciones; validar el mecanismo de bloqueo según art. 32 LOPDGDD cuando proceda.
- Obtener autorización separada para migraciones, despliegue, cambios de permisos y cualquier tratamiento de datos reales.

**Criterio de cierre de este documento:** diseño verificable con puertas explícitas. **No significa que SEC5-PRIV-011/012/013 esté jurídicamente cerrado ni operacionalmente implantado.**
