# ANALYTICS-PRIV-001 — Auditoría de estadísticas, valor de negocio y minimización

**Estado:** diagnóstico técnico y contrato de requisitos de producto, **no implementado**.  
**Fecha:** 01/11/2026. **Base auditada:** `main@0307dfdf382e2d6d024201a99a2fd2b100415f87`.  
**Propietario:** Mariano Sevilla. **Documentación fiscal profesional:** custodiada por Rafael Ramos según aclaración del titular.  
**Alcance:** código Flask/ORM, rutas y paneles; **sin consultas de datos reales**, exportación de usuarios, cambios de esquema, purgas, comunicaciones, modificación de producción ni acceso a proveedores.

## 1. Decisión de producto

marianosevilla.com es un portal de intermediación con Rafael Ramos y de generación de informes FIFO, **no un archivo documental del asesor**. Necesita una analítica potente para priorizar compatibilidad, mejorar importación y UX, medir demanda, capacidad, conversión y rentabilidad. **No necesita mostrar ni reconstruir las tareas de cada usuario identificado con fines estadísticos.**

Separar:
- **Operación individual:** cuenta, autenticación, descarga adquirida, soporte de incidencias, solicitudes, comunicaciones consentidas, pagos/reembolsos y evidencia necesaria. No clasificar estas filas como anónimas ni eliminarlas solo porque no se requieren para un gráfico.
- **Analítica:** indicadores, cohortes y tendencias agregadas con finalidades definidas. El vínculo técnico temporal para deduplicar, si llegase a necesitarse, no es anónimo mientras permita identificar a una persona.
- **Temporales:** CSV/Excel originales y PDF FIFO, con ciclo de vida y límites distintos. La ausencia de un volumen web en Railway no demuestra borrado garantizado ante cualquier fallo.

El contrato anterior **no aprueba plazos**: los 30/90/180 días de los documentos SEC5-PRIV son hipótesis de revisión, no mandatos legales. No cambiar datos históricos antes de una decisión por finalidad y de pruebas.

## 2. Inventario exhaustivo de 17 tablas ORM (no son 17 tablas de estadísticas)

| Tabla ORM | Papel en la plataforma | Tratamiento propuesto para la auditoría futura |
|---|---|---|
| `users` | Cuentas, acceso, roles, preferencias | Operativo: usar conteos y períodos agregados para analítica; conservar acceso y soporte según finalidad |
| `fifo_reports` | Eventos de creación/descarga, metadatos y resultados económicos individuales | Fuente analítica principal: conteos, tendencias, errores, duración, exchanges y complejidad; revisar importes vinculados a `user_id` |
| `processing_errors` | Incidencias con referencias al usuario/email y posibles textos diagnósticos históricos | Soporte operativo separado del panel agregado; contar clases/etapas y resoluciones sin exponer emails |
| `incidents` | Agrupación técnica por huella y estado | Operativo/observabilidad: métricas agregadas de incidencias; revisar notas libres |
| `contactos` | Consultas con email/IP/mensaje | Operativo: conteos por tipo, estado y tiempo de respuesta; no convertir texto libre en analítica nominativa |
| `fiscal_advisory_requests` | Intermediación y estado del expediente, datos de contacto y posible evidencia económica | Operativo: embudo de solicitudes por estado/servicio y pagos conciliados; separar ingresos del profesional y comisión de Mariano |
| `s01_stripe_checkout_attempts` | Intentos de pago, idempotencia y estado | Operativo financiero: usar solo para métricas verificables tras conciliación, proteger disputas |
| `s01_stripe_event_receipts` | Prueba de eventos/webhooks y deduplicación | Operativo financiero: no purgar por estadística ni asumir que recepción implica liquidación |
| `s01_stripe_notification_outbox` | Envíos/reintentos de notificaciones económicas | Operativo: métricas agregadas de entrega, preservar evidencias necesarias |
| `fiscal_advisory_files` | Metadatos/rutas de posibles adjuntos históricos | Operativo y custodia a validar; subida nueva deshabilitada, no presumir que filas/ficheros reales no existen |
| `fiscal_advisory_status_history` | Historial de estados de solicitudes | Operativo: calcular duraciones agregadas sin exponer trayectorias individuales en el panel |
| `advisory_internal_notes` | Texto interno de gestión | Operativo confidencial; no fuente de analítica general |
| `advisory_audit_log` | Trazabilidad de cambios | Evidencia operativa; no confundir con tracking de producto |
| `communication_campaigns` | Borradores y campañas | Operativo: conteos agregados si se habilita comunicación legítima |
| `communication_deliveries` | Estados de correo y destinatarios | Operativo: tasas agregadas de entrega, conservar evidencia de oposición cuando proceda |
| `resources` | Catálogo | Editorial: métricas de demanda de recursos sin asociar actividad individual |
| `resource_requests` | Peticiones de recursos, UID/email/Telegram y opciones | Operativo: conteos/conversión agregados; no usar consentimiento antiguo forzoso como autorización de marketing |

**Limitación:** clasificación del ORM, no de todas las tablas físicas, ficheros, proveedores, copias o datos efectivamente existentes. La matriz de retención en `docs/security/SEC5_PRIV_011_013_RETENTION_MATRIX.md` sigue siendo la referencia de privacidad.

## 3. Estadísticas existentes, fuentes reales y precisión semántica

- `GET /stats` y `GET /api/stats` son **solo para administradores** y consumen agregaciones de `User`, `FifoReport`, `Contacto`, `FiscalAdvisoryRequest`, `ProcessingError`. Código: `app.py`, `stats_page`, `api_stats`, `_api_stats_data`.
- **Ya disponibles:** altas, verificación, usuarios con informes, distribución temporal, informes por exchange/ejercicio, volumen, éxito/fallo, descargas, tiempo de cálculo, errores por causa, complejidad/multi-exchange, segmentos agregados y estados de asesoramiento. Mantenerlos durante el rediseño, sin suprimir una fuente antes de revisar dependencias.
- **Hallazgo PRIV-1:** `_api_stats_data` construye `top_usuarios` con `user_id` y `email_mask`; la interfaz muestra correos truncados. **Un email parcialmente oculto junto a un ID y conteo individual no equivale a anonimización.** Eliminar la clasificación nominal del panel analítico solo mediante una intervención de runtime separada, con prueba de regresión.
- **Hallazgo PRIV-2:** `errores.detalle` e `errores.processing_errors` retornan listas de incidencias (fechas por minuto, emails parcialmente ocultos, IDs, descripciones, huellas). Son útiles para **soporte**, no para analítica de negocio. Reubicar el acceso al expediente individual en el flujo administrativo autorizado; para /stats ofrecer conteos agregados por exchange/categoría/estado/fecha. No eliminar la capacidad de contactar y resolver casos.
- **Hallazgo MÉTRICA-1:** `usuarios.activos_30d` usa `users.last_login`; mide **accesos recientes registrados**, no usuarios activos realizando acciones. Renombrar o redefinir tras especificación de evento. `usuarios.con_informes` identifica quienes han generado al menos un informe, no necesariamente quienes lo descargaron.
- **Hallazgo MÉTRICA-2:** `asesoramiento.pagadas` usa un conjunto de **estados administrativos** (`paid_received`, `under_review`, `waiting_user_info`, `in_progress`, `completed`); `conversion_pct` no es automáticamente tasa de **cobro conciliado**. `ingresos_total_eur` suma `amount_paid` de solicitudes y puede representar importe abonado al profesional, **no comisión ni ingreso neto de Mariano**. Validar estado Stripe, reembolsos, impuestos y reparto antes de usar estas cifras para rentabilidad.
- **Hallazgo MÉTRICA-3:** `/stats-v2` y `/api/stats-v2/encuentro` son admin-only, pero devuelven `ENCUENTRO_FIXTURE` de `stats_v2_fixture.py`: **datos de escenario, no mediciones reales**. Prohibido mostrar sus porcentajes como KPI observados.
- **Hallazgo MÉTRICA-4:** el panel calcula múltiples tendencias a partir de marcas individuales `created_at` cargadas a Python; evaluar agregación SQL y coste de consultas antes de elevar tráfico, sin optimización prematura ni cambios de arquitectura ahora.
- **Hallazgo ANALÍTICA-1:** el inventario de 17 tablas no incorpora un registro general de eventos del embudo. La ruta actual acredita generación y descarga de informes, pero por sí sola no distingue todos los abandonos entre visita, registro, carga, validación, vista previa y pago.

## 4. Contrato del futuro panel analítico

| Prioridad | KPI o embudo | Definición verificable y fuente mínima |
|---|---|---|
| P0 | Altas, verificación y cuentas con un primer informe | Contar eventos operativos actuales; distinguir altas totales de usuarios únicos que completan un informe |
| P0 | Informes iniciados, generados, bloqueados, fallidos y descargados | Definir cada transición y denominador; no mezclar fallo de formato con error interno ni descarga con generación |
| P0 | Demanda y compatibilidad por exchange, año, formato | Agregar cuentas e informes sin exponer registros individuales, series temporales consistentes |
| P0 | Rendimiento y calidad | Mediana, p95 y tasa de fallos por exchange/formato; mínimo muestral para interpretar tasas |
| P0 | Monetización 2027 | Precio mostrado, compra confirmada, reembolso, derecho de descarga, ingresos brutos y netos: solo eventos Stripe conciliados del **producto FIFO**, separado de asesoramiento |
| P1 | Embudos de uso y conversión | Contadores por etapa y ventana; una tasa de conversión de la misma cohorte requiere deduplicación/correlación controlada, **no se deduce** dividiendo eventos de días o universos diferentes |
| P1 | Retención por cohortes | Preferir cómputo agregado con vínculo temporal mínimo documentado; revisar base jurídica y período antes de instrumentar seguimiento pseudónimo |
| P1 | Coste/rentabilidad por informe y exchange | Medir recursos y proveedor; estimar margen con costes verificables, no inferirlo de `amount_paid` de Rafa |
| P2 | Recursos y consultas | Recuento de solicitudes, finalización, tipos, tiempos agregados; sin conservar datos de contacto para analítica |

No crear nuevas tablas por anticipación. Priorizar primero una **capa de lectura agregada**, métricas SQL y diccionario de eventos; recoger nueva telemetría solo tras demostrar qué KPI falta. Los requisitos de monetización pueden exigir evidencia individual de compra y acceso **fuera de la analítica**.

## 5. Privacidad y controles mínimos para una implementación posterior

1. Agregación por defecto; prohibir `user_id`, email, NIF, IP, nombres de fichero, importes fiscales por usuario, descripción del expediente y huellas vinculables en respuestas del **panel analítico**. Mantener soporte individual en rutas/roles operativos separados, auditados.
2. Celdas o segmentos pequeños: evaluar umbral y supresión/agrupación en función del riesgo real, sin presentar un umbral técnico como anonimización garantizada. Evitar que filtros solapados y series temporales reconstruyan identidades.
3. Distinguir totalmente anónimo de seudonimizado. La identidad temporal para deduplicar cohortes sigue siendo dato personal mientras exista enlace recuperable; definir base jurídica, período y acceso antes de implementarla.
4. Separar errores técnicos de contenido libre, correos y archivos; no retener CSV original para analítica ni sus resultados fiscales identificables sin finalidad adicional justificada.
5. Ventanas de consulta de 7/30/180 días pueden ser **ventanas analíticas**, no plazos de eliminación autorizados. Política de conservación por finalidad todavía pendiente en `SEC5-PRIV-011/012/013`.
6. Filtrar datos de administradores y pruebas **por rol/evidencia comprobable**: hoy parte del filtrado depende de lista de emails admin y en errores de email, lo que puede no excluir filas antiguas/anónimas. Auditar denominadores y criterios antes de confiar en conversión.
7. Aceptación con datos sintéticos: regresiones para 0 datos, fecha límite, descarte de identificadores, acceso no-admin 403/redirect, dispersión en segmentos pequeños, denominadores correctos, escenarios de devolución/cobro no conciliado, y mantenimiento del flujo de soporte separado.
8. No afirmar cumplimiento legal completo por pasar CI. La política de tratamiento y conservación requiere revisión jurídica y verificación externa por proveedor.

## 6. Ejecución incremental que se propone, no autorizada

**Entrega siguiente A (mínima):** separar de `/api/stats` el ranking nominativo `top_usuarios` y las listas de incidencias; conservar agregados y mover las acciones de soporte a interfaz de operación autorizada sin pérdida funcional. Proteger contrato HTTP y frontend con pruebas. **Requiere revisión del uso real del panel y autorización de integración.**

**Entrega B:** diccionario de métricas y corrección de etiquetas de actividad, conversión e ingresos; contrastar Stripe y estado operativo real antes de exponer KPI financieros.

**Entrega C:** cuando se apruebe el modelo comercial FIFO, diseñar métricas del embudo y compras, respetando agregación y una correlación temporal solo si su beneficio justifica el tratamiento.

**No realizado:** cambios en tablas, rutas, funcionalidades, sistema de pagos, soporte, borrados, retención, permisos, cookies o despliegue. Esta auditoría es **estática** y no valida valores cuantitativos de producción ni rendimiento con datos reales.
