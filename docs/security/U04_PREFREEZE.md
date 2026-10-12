# Fase 5 · U04-PREFREEZE

Base autorizada: `56882073295faae3bd1bc3632288a970acb330da` (`main`). Rama: `security/fase5-u04-prefreeze`. Entrega exclusivamente en PR en borrador. Sin autorización de merge, despliegue, variables, credenciales, migración productiva ni operaciones reales. La PR #29 permanece intacta.

## Investigación y decisión

Se inspeccionaron todas las referencias a modelos de asesoramiento y las escrituras/llamadas PayPal y Stripe en los módulos Python, las rutas Flask, modelos, relaciones/cascades, tests, `required-ci.yml`, `Procfile` y `bootstrap_db.py`. El árbol inicial estaba limpio, sin archivos sin fusionar y sin AGENTS.md versionado. Base exacta comprobada también contra GitHub.

La creación y captura PayPal usan POST externos; la aceptación se modifica antes de crear la orden. Reemitir un presupuesto borra los IDs PayPal. Los webhooks pueden confirmar pagos y reembolsos. Stripe puede confirmar `checkout.session.completed`, escribir el PaymentIntent y llamar al mismo finalizador de pago; no hay creación de Checkout/PaymentIntent en este árbol. Su fallback sin secreto de firma es inseguro si se habilita: queda inaccesible, no se corrige ni se reactiva en esta entrega.

Mensajes escriben notas, auditoría e historial y pueden cambiar estado. Notas modifican `updated_at`; `is-test` modifica la clasificación de los ingresos/expediente. Uploads agregan documentación y pueden sustituir un archivo con el mismo nombre. Delete elimina expediente y evidencia por cascade. Se suspenden todas esas modificaciones de expedientes existentes, incluso mensajes sin cambio de estado. La consulta autorizada continúa.

La entrada de nuevas solicitudes se mantiene: fija `submitted`, no presupone ni confirma pagos, no acepta estado/importe/IDs del body ni altera un expediente existente. Sus emails son de recepción. Perfil, NIF y anonimización de cuenta modifican `users`, no las copias de identidad/facturación de `FiscalAdvisoryRequest`, ni sus IDs, importes, presupuesto o evidencias; el user_id se conserva. No hay tareas programadas/worker financiero en el Procfile ni otra integración de cobro encontrada.

## Implementación y archivos

- `fiscal_app_export/advisory_prefreeze.py`: denegación incondicional reutilizable, sin lectura de configuración para reactivar; respuesta genérica `503`, `no-store`, `Retry-After: 300` (orientativo); defensa de auxiliares mediante excepción anterior al I/O.
- `fiscal_app_export/app.py`: 12 rutas protegidas, auxiliares PayPal/finalizador protegidos; página sin caché. Decoradores de autorización y límites existentes conservados y exteriores al bloqueo.
- `fiscal_app_export/static/pagar.html`: aviso estático en español, sin botón, formulario, script de pago ni instrucciones para repetirlo; funciona sin JavaScript.
- `fiscal_app_export/tests/qa_advisory_prefreeze.py`: Flask/ORM U03 real, snapshots de cinco tablas y detector SQL, mocks que fallan ante proveedores/emails, replay, permisos, 56 peticiones en dos tandas simultáneas de 28, auxiliares, páginas y consultas.
- `fiscal_app_export/tests/test_advisory_prefreeze.py`: runner con entorno nuevo, credenciales ficticias y SQLite efímero; bloqueo de red.
- `fiscal_app_export/tests/qa_advisory_prefreeze_postgres.py`: el mismo conjunto contra PostgreSQL efímero de CI, DSN local fijo, nunca Railway.
- `fiscal_app_export/tests/qa_advisory_prefreeze_browser.py`: Chromium, 320/375/768/1440 px, JavaScript activado y desactivado, aviso visible, sin cobro, sin overflow ni proveedor.
- `fiscal_app_export/tests/test_advisory_delete.py`: expectativas de conservación y suspensión, sin perder pruebas de roles.
- `fiscal_app_export/tests/test_advisory_mensaje.py`: expectativas de suspensión sin email, cambios, notas o historial, manteniendo autorización.
- `.github/workflows/required-ci.yml`: añade pruebas PostgreSQL/browser a los jobs obligatorios existentes; sin permisos nuevos, secrets, despliegues o cambio de pins.
- `docs/security/U04_PREFREEZE.md`: perímetro, justificación, recuperación y condiciones de entrega.

No se modifican modelos, migraciones, bootstrap, Procfile, requisitos ni esquema. La revisión Alembic sigue siendo `v5w6x7y8z9a0`.

## Matriz de rutas

| Ruta | Comportamiento PREFREEZE |
|---|---|
| POST `/api/pago/iniciar/<token>` | 503 JSON; no aceptación, query de expediente, creación de orden ni proveedor |
| GET `/api/pago/paypal/capture` (incluye HEAD) | 503 HTML mantenimiento; argumentos no usados, ninguna captura |
| POST `/api/webhooks/paypal` | 503 sin analizar/verificar/procesar/almacenar payload; pagos y reembolsos retenidos por proveedor |
| POST `/api/webhooks/stripe` | 503 sin confirmar pagos ni falsos acuses, incluso sin SDK/clave |
| GET `/api/pago/info/<token>` | 503 genérico, `reconciliation_pending`; evita presentación antigua de pendiente/reintento/caducidad como evidencia negativa |
| POST `/api/admin/asesoramiento/solicitudes/<id>/enviar-presupuesto` | Usuarios autorizados: 503; no nueva oferta, importe, token, estado ni borrado de IDs |
| POST `/api/admin/asesoramiento/solicitudes/<id>/estado` | Autorizados: 503 para cualquier transición |
| DELETE `/api/admin/asesoramiento/solicitudes/<id>` | Admin: 503; sin borrado/cascade/auditoría de borrado ficticia; advisor/user: 403 |
| POST `/api/admin/asesoramiento/solicitudes/<id>/mensaje` | Autorizados: 503 con flag true, false, ausente o malformado; sin email ni historial |
| POST `/api/admin/asesoramiento/solicitudes/<id>/nota` | Autorizados: 503; no nota ni modificación de updated_at |
| POST `/api/admin/asesoramiento/solicitudes/<id>/is-test` | Admin: 503; no cambio de clasificación |
| POST `/api/asesoramiento/files/<id>` | Autenticado: 503; sin archivo ni registro, aun habilitando uploads |
| GET `/pagar/<token>` y HTML estático | Aviso sin pago, sin JS necesario; la ruta pública aplica no-store |
| GET lista/detalle admin, mis solicitudes y descarga autorizada | Consultas y controles de acceso originales; no se abren nuevas autorizaciones |
| POST `/api/asesoramiento/solicitar` | Recepción de una nueva solicitud `submitted`, sin cobro ni modificación de otra |
| Autenticación/FIFO/721/estadísticas/públicas/resto | Código funcional conservado; regresión completa y navegación de CI |

Los 503 administrativos se producen después de comprobar sesión/rol y antes de cargar el expediente. Anónimos siguen recibiendo 401; roles denegados 403. La suspensión precede a la comprobación de existencia. Para uploads, se deniega a todo autenticado sin divulgar existencia/propietario. OPTIONS de Flask no procesa una operación ni confirma un webhook; no es un acuse de POST. Un límite anterior puede responder 429 y un host canónico puede redirigir: ninguno produce cobro ni escritura; las pruebas se hacen en el endpoint canónico sin agotar el límite.

## Webhooks: plazos y recuperación propuesta

Fuentes oficiales consultadas el 11/12 de octubre de 2026:

- PayPal: https://developer.paypal.com/api/rest/webhooks — non-2xx provoca hasta 25 reintentos durante 3 días; después puede reenviarse manualmente desde Webhook Events.
- Stripe: https://docs.stripe.com/webhooks — live hasta 3 días con backoff; sandbox 3 intentos en unas horas. Reenvío Dashboard hasta 15 días y CLI hasta 30 días. Reenvío manual no cancela necesariamente reintentos automáticos. No hay orden ni entrega única garantizados.

503 declara incapacidad temporal sin aceptar ni procesar. Se evita incluso la llamada PayPal de verificación: en esta versión no se confía ni se actúa sobre el cuerpo; no se conserva PII/payloads ni se fabrica una cola local. Al recuperar, el nuevo receptor tendrá que verificar firmas actuales/autenticidad y conciliar contra el proveedor, nunca confiar en un payload guardado sin verificar. `Retry-After` no amplía las ventanas ni impone el calendario del proveedor.

Los eventos no se guardan localmente: la conservación depende del proveedor y sus límites. Propuesta para autorización posterior: registrar inicio UTC/ventana de eventos, comprobar fallos y próxima entrega en ambos proveedores, preparar inventario de eventos/órdenes/capturas/sesiones pendientes con evidencia, y revisar la duración antes de consumir el presupuesto de reintentos. Plan operativo prudente: revisión a las 24 h y escalado antes de 48 h, sin tratar 72 h como garantía (eventos anteriores pueden agotar antes su ventana). Esta propuesta no programa alertas ni consulta cuentas.

Tras validar el receptor U04 con cobros desactivados, conciliar las mismas órdenes mediante lectura y reenviar eventos fallidos solo por una vía autorizada e idempotente. No volver a U03 para procesar el backlog, no emitir otra orden ni repetir capture. PayPal aprobado no demuestra cobro ni ausencia de cobro; captura anterior con ACK perdido sigue incierta. Preservar expedientes/IDs/evidencia. Si los eventos ya no pueden recuperarse, acudir a evidencia del proveedor y revisión manual; no sustituirlo por inferencias negativas.

Stripe debe seguir suspendido al integrar U04 salvo revisión/autoridad explícita de una vía segura de autenticación, asociación, importe y deduplicación. La conciliación PayPal de #29 no demuestra por sí sola seguridad de recuperación Stripe. No se garantiza ausencia de duplicados tras una reactivación futura fuera del alcance: se prohíbe reactivar hasta acreditarla.

## Comprobar retirada completa de U03 (solo autorización posterior)

1. Certificar configuración real de servicio/entorno, número de réplicas y SHA exacto de PREFREEZE. Congelar nuevas intervenciones/rollback al código vulnerable durante la transición.
2. Revisar la estrategia real de sustitución y el drenaje. Una réplica, un estado Successful y una respuesta 503 no prueban ausencia de workers antiguos.
3. Identificar todos los deployments/instancias/containers/workers que ejecutaban U03 (incluidos reinicios y otros consumidores si se descubren). Acreditar su estado terminal y terminación de todos los procesos Gunicorn; no basta quitar tráfico al deployment.
4. Verificar fin de solicitudes/transacciones anteriores y de las llamadas externas ya iniciadas. Procfile: 1 worker gthread, 8 threads, timeout 120 s y graceful-timeout 30 s; una espera por reloj no prueba muerte de procesos y no descarta que el proveedor cobrara antes de su terminación.
5. Probar de forma autorizada endpoints canónicos y mantenimiento, sin operación financiera real, y correlacionar con instancias nuevas. Comprobar que no existen procesos/consumidores U03 conectados o activos. El registro de identidad de proceso/SHA puede requerir instrumentación o evidencias adicionales, no implementadas aquí.
6. Emitir evidencia escrita del corte y mantener suspensión. Solo entonces considerar migración/arranque U04 con nueva autorización y backup restaurable. Las operaciones iniciadas antes del corte se concilian por U04, no se dan por inexistentes.

PREFREEZE no puede frenar a U03 durante SU propio despliegue inicial ni cancelar un POST ya enviado. Si no puede acreditarse la retirada/drenaje, cancelar la migración U04 y obtener un procedimiento autorizado que garantice el corte; no asumir que un tiempo de espera o un flag basta.

## Compatibilidad con PR #29 y condiciones de cancelación

La PR #29 se ha consultado únicamente en lectura (head `75b5a6a9b799691fb9e0a2b529991f9f942fdd0e`, draft/open). No se actualiza, rebasa ni integra. PREFREEZE usa U03; las guardas no requieren campos U04. Una integración posterior deberá resolver solapamientos de app/tests preservando el bloqueo y demostrar la compatibilidad con migración aditiva, sin downgrade ni rollback a U03 vulnerable. Los auxiliares bloqueados deben revisarse expresamente en esa integración: dejarlos intactos conserva suspensión, retirarlos sin alternativa segura reactiva caminos peligrosos.

Cancelar cualquier despliegue/migración posterior ante: base/artefacto distinto, CI fallida o no evaluada, migración imprevista, retiro de U03 no probado, requerimiento de cambio de proveedor/configuración no autorizado, imposibilidad de recuperar/conciliar eventos, cualquier camino de cobro o escritura fuera del bloqueo, modificación de esquema incompatible, ausencia de backup verificable o necesidad de reactivar Stripe/U03 para recuperar. Ante incertidumbre financiera mantener la suspensión.

## Validación

El runner específico ejecuta 65 pruebas sin skips en SQLite y se incorpora idéntico a PostgreSQL 18 de CI. Las 56 peticiones concurrentes repiten toda la matriz con proveedores configurados y mocks que fallan ante cualquier llamada; snapshots de cinco tablas permanecen iguales. Se detecta SQL DML financiero y se prueba además que las denegaciones no cargan registros financieros. La batería de Python completa y los tres jobs obligatorios deben llegar a estado terminal antes de la entrega; los resultados exactos, SHA final y URL se registran en el informe externo de entrega para no cambiar el commit ensayado solo al documentar sus propios resultados.
