# Auditoría de situación y plan maestro — marianosevilla.com · S01 / S02

**Fecha de corte:** 13 de octubre de 2026. **Modalidad:** inspección de código y PR de GitHub de solo lectura; **SIN** acceso a bases productivas, Railway, Stripe/MERU/PayPal, correos de clientes ni CSV.  
**Estatus:** BASELINE PRELIMINAR, no certifica el estado de despliegue ni los fondos. La auditoría operativa queda pendiente de autorizaciones de lectura mínimas.  
**Rama base:** `main` SHA `56882073295faae3bd1bc3632288a970acb330da`. Este documento no es implementación.

## 0. Objetivo y límites

Transformar el proyecto de desarrollo acumulativo en **dos productos autónomos y un plan de integración auditable**, con decisiones de negocio antes de activar funciones, responsable definido, evidencia verificable y gates de GO/NO-GO.

- **S01, intermediación de asesoramiento fiscal:** Rafa autónomo, asegurado y responsable del servicio profesional y de la facturación que emite externamente. Mariano proporciona audiencia y plataforma de contacto, presupuestos y pago; cobra remuneración por intermediación. NO se factura desde la app.
- **S02, informes FIFO:** producto propio de Mariano con objetivo de monetizar las descargas desde **01/01/2027**, sin elegir suscripción/plan por conjetura; se requieren estadísticas agregadas reales y modelo de derechos. El posible Modelo 721 necesita decisión de producto **separada**.
- No suponer que una cuenta MERU con IBAN configurado en Stripe prueba abonos ya liquidados, compatibilidad de Rafa o viabilidad de Connect. El propietario confirma que **su Stripe existente ha aceptado el IBAN MERU**; esta evidencia se respeta.

## 1. Nuevas reglas económicas y discrepancia a cerrar

**Comisiones del procesamiento de Stripe: regla empresarial nueva = Mariano 30 % / Rafa 70 % del gasto REAL por cargo S01.** La PR #54 fue diseñada y probada con 50/50 y queda SUPERADA; se ha marcado en su descripción como no apta para implementar la nueva regla, sin alterar el historial.

**AMBIGÜEDAD CRÍTICA: cuota de ingresos del 30 %.**
- `honorarios Rafa = 200 €; añadir 30 % de estos = 60 €; cliente paga 260 €` da Mariano **23,08 % del precio total**, Rafa **76,92 %**.
- Si Rafa debe recibir 200 € como **70 % del total**, total `200 / 0,70 = 285,714… €` (a céntimos 285,71 €); Mariano recibe 85,71 €. Los impuestos reales y tarifas de Stripe aún no están incluidos.
- Por tanto **30/70 sobre el procesamiento** es una regla confirmada, pero **la base de la remuneración de Mariano debe confirmarse expresamente** (30 % de honorarios Rafa o 30 % del precio total). No «corregir» automáticamente ambas reglas para hacerlas coincidir.

Ejemplo de gastos hipotéticos: si Stripe cobrase `4,15 €` por un cargo, al 30/70 y redondeando el céntimo a Mariano, Mariano soporta **1,25 €**, Rafa **2,90 €**. La tarifa real de cualquier operación se consultará en la balance transaction del cargo de Rafa, no se inferirá de una estimación.

## 2. Inventario verificable del estado del código

| Dominio | Verificado en `main` | Preparado fuera de `main` | Brecha / decisión |
|---|---|---|---|
| Infraestructura | Flask/PostgreSQL/Railway, `Procfile` invoca `python bootstrap_db.py` en arranque | #45 backup PG18, #49 arranque sin DDL con gate, ensayo local propietario PASS | No desplegar cambios de migración sin corte y backup nuevo; revisión independiente de órdenes y cabezas Alembic |
| Captación S01 | POST `/api/asesoramiento/solicitar` autenticado; expediente `FiscalAdvisoryRequest`; panel `/admin/asesoramiento` | #33 y siguientes, orquestación sintética | Validar roles y acceso exclusivo de Rafa al detalle fiscal, ciclo real y políticas de retención |
| Presupuesto S01 | Ruta `/api/admin/asesoramiento/solicitudes/<id>/enviar-presupuesto` emite inmediatamente `/pagar/<token>` | #50–#52 simulan consentimiento/reserva atómicos, #53 contrato G06 | **No corresponde al flujo deseado**: primero aceptar presupuesto, después operador autoriza/genera/envía enlace; separar aceptación durable de creación de Checkout sin segundo cobro |
| Pagos antiguos | `app.py` contiene funciones de PayPal create/capture y webhook; webhook Stripe permite parseo JSON sin firma si no hay secreto | #29 U04, #30 PREFREEZE, #32 firma obligatoria, #37/40 webhook/outbox, #41 retirada PayPal, #43/44 carreras | Riesgo crítico si se usa código antiguo sin integrar. **No verificar ni asumir qué está habilitado en entorno** solo leyendo GitHub |
| Precio S01 | `quoted_amount` centésimos simple | #33 calcula Rafa + 30 % de honorarios; #53 modelo de oferta y aceptación | Base 30 % por aclarar; IVA/precio final, comerciante contractual, contrato y facturas Rafa; no aceptar ejemplos como decisión fiscal |
| Connect y remuneración | **No disponible** como flujo operativo en `main` | #54 fórmula 50/50 OBSOLETA; Stripe direct charge con application fee propuesto | Diseñar cuentas Rafa (onboarding/KYC), `application_fee_amount`, cargo directo, gastos 30/70 y ajuste contable, exactamente una conciliación y sin API real aún |
| Informes FIFO S02 | `FifoReport` registra por usuario/exchange/ejercicio, estado, métricas procesamiento y `downloaded_at`; `/api/descargar/<token>` autentica y consume token, **sin paywall** | No consta un derecho de pago S02 integrado | Definir entitlement por producto/ejercicio/intercambios, regeneraciones y errores, precio basado en datos, derecho de usuarios anteriores |
| Estadísticas | `/api/stats` protegido `require_admin`, métricas de informes y usuarios; BD almacena datos históricos | #45/47 ensayos limitados localmente en copia del 10/10 | Para decisión de tarifa hace falta **agrupación anonimizada** por usuario, cohortes, descargas y repetición; no publicar emails/CSV/PII |
| Webhooks/eventos | Manejo Stripe en `main` no representa Connect multicuenta | #32/37/40 firma/idempotencia y pruebas sintéticas | Validar `event.account`, cuenta de Rafa, order/paymentIntent/charge, importes, capturas y estados `paid`, notificaciones, deduplicación y disponibilidad |
| Devoluciones | Modelo S01 incluye estados `refunded`; no hay liquidación completa Connect | Protocolos de reconcilio y estado incierto en PR de test | Política jurídica, disputa, chargeback, refund al cliente, reversión de application fee y ajustes de gastos sin doble crédito |
| Seguridad y releases | `main` es un conjunto anterior a las PR S01 | PR #29–#54 **sin fusionar** (verificadas #29–#54 pertinentes; #31–#40 también abiertas) | Consolidar dependencias, buscar conflictos, matriz regresión/retirada, plan rollback, tests PROD-simulado, rollout staged; evitar activar Live por flags |
| Payout MERU | Usuario afirma que Stripe aceptó IBAN MERU de su cuenta | Sin prueba de payout ni cuenta Rafa conectada | Distinguir IBAN aceptado, payout habilitado, transferencia liquidada y limitaciones contractuales del banco |

**Advertencia:** GitHub `main` no acredita por sí solo el commit realmente corriendo en Railway, la revisión BD productiva, el estado de claves/webhooks, ni proveedores. Una auditoría operativa posterior deberá probar esos datos con acceso READ ONLY expresamente autorizado y sin exponer secretos.

### Registros y evidencia anteriores

- #49 G04: PR borrador, CI #71 SUCCESS, ensayo local realizado por el propietario sobre copia del 10/10 con `S01 REHEARSAL: PASS`. Es una validación de código/backup, **no** autorización de deploy.
- #50–#52: flujo HTTP sintético y remediación AUD-001/AUD-002, CI #75 1.482 PASSED, pruebas de concurrencia PG18; falta transformar el diseño para **aceptación separada del enlace en panel**.
- #53: contrato sintético G06, CI #76 1.535 PASSED, pero decisiones fiscales/merchant/consentimiento real no cerradas.
- #54: CI #78 1.564 PASSED, PR borrador, **cálculo 50/50 superado** por la regla comercial de 30/70 del propietario.
- Inventario local histórico de copia 10/10: 6 expedientes, cero señales PayPal; propietario informa que **nunca ha efectuado un cobro PayPal en la web**. No es evidencia provider-level universal ni actual. G05 queda formalmente pendiente solo del contraste proporcionado que se acuerde, **sin exigir exposiciones privadas innecesarias**.

## 3. Secuencia operativa S01 — criterios de aceptación de producto

1. Cliente autenticado envía formulario y recibe acuse sin datos sensibles.
2. Rafa recibe un expediente con acceso restringido y determina honorarios/alcance.
3. Panel muestra desglose e importe final aprobado, IVA y condiciones; envía **presupuesto, no enlace de pago**.
4. Cliente identifica presupuesto/version, lee condiciones y acepta expresamente; estado persistente `quote_accepted`, sin pago ni orden externa.
5. Rafa o perfil autorizado pulsa **Generar enlace de pago** para ese presupuesto aceptado. Una reserva duradera única con idempotency key antes de llamar a Stripe; no reemitir si resultado incierto.
6. Stripe Checkout opera como cargo **directo** a la cuenta conectada de Rafa; `application_fee_amount` para la remuneración bruta de Mariano. No llamar a Stripe real antes de Connect Test expresamente autorizado.
7. Confirmación del pago verificada por webhook **firmado**, cuenta conectada y conciliación de importe/método con Stripe API, nunca retorno del navegador; Rafa recibe aviso y puede iniciar servicio.
8. En proceso contable separado se obtiene comisión de procesamiento real de balance transaction y se compensa el **30 % a cargo de Mariano**, con redondeo acordado y una única devolución parcial de application fee a cuenta de Rafa si Stripe lo permite. **No es refund al cliente**. Debe ser idempotente y reversible auditadamente.
9. Rafa presta servicio y emite factura **fuera de la app**. Estados de solicitud y fiscalidad no se mezclan con la contabilidad de pagos o con S02.

**Invariantes de seguridad:** importes en céntimos; historia inmutable; no pagos sin aceptación; no dos sesiones/cargos ante timeout; cancelación y reembolso con conciliación real; ninguna credencial bancaria ni clave en logs; no permitir a un usuario acceder al expediente ajeno; cierre de sesión y rotación de tokens; principio mínimo de datos personales.

## 4. Producto S02 — descubrimiento y pruebas de monetización

**Objetivo comercial:** introducir control de descarga de informes FIFO desde el **01/01/2027**, sin política de precio/plan elegida aún. Preguntas de producto:
- ¿Pago para **generar** el informe o para **descargar** el PDF? Si solo descarga, ¿qué resultados sensibles/permanentes se muestran antes?
- ¿Qué es una unidad cobrable: usuario, campaña IRPF, ejercicio fiscal, exchange, fichero CSV o informe? ¿Se permite regenerar sin recobro?
- ¿Devolver crédito ante error técnico o informe inconsistente? ¿Permitir re-descarga de compras históricas?
- ¿Precio anual por ejercicio, pago por informe, créditos o híbrido? ¿Usuarios anteriores y promociones, cupos o descuentos?
- ¿También queda de pago Modelo 721 y otras herramientas? Debe decidirse explícitamente.

**Análisis agregado privado propuesto antes de fijar precios:**

- Usuarios y cohortes por mes, primera vs última actividad.
- Informes generados por usuario (percentiles P50/P75/P90/P95, 1; 2–3; 4–10; >10), descargas iniciadas por usuario.
- Estacionalidad mensual y por ejercicio, recurrencia fuera de Renta, número de exchanges distintos por usuario y por ejercicio.
- Informe exitoso vs fallido, número de reintentos o regeneraciones por combinación usuario-exchange-ejercicio, complejidad `csv_rows/fifo_operations/processing_ms`.
- Distribución de gasto computacional y soporte; costes de Stripe contra posible ticket; escenarios realistas de conversión 2/5/10/20 %, no «predicción» sin datos.
- Telemetría de descargas indica inicio y consumo del token, **no finalización garantizada**; evitar presentarla como venta o satisfacción.
- Datos agregados publicables con supresión de celdas pequeñas; sin email, nombre, IDs identificables, resultados fiscales individuales, órdenes ni CSV.

## 5. Matriz de riesgos y prioridades

| ID | Riesgo | Prioridad | Condición de salida |
|---|---|---|---|
| B01 | Ambigüedad del 30 % en el **precio total** | **P0 — Decisión propietario** | Fórmula formal aprobada en céntimos, ejemplos de 200 y 1.000 €, IVA separado |
| B02 | Quién factura qué y merchant-of-record de S01 | **P0 — Rafa/asesor fiscal** | Acuerdo y muestra de factura/registro **externos**, sin crear facturas en app |
| B03 | Código `main` histórico permite caminos PayPal y Stripe sin firma si no hay secreto | **P0 — Seguridad antes de desplegar S01** | PREFREEZE, firma obligatoria, retirada ejecutable, reconciliación y prueba deploy no transaccional |
| B04 | PR #54 calcula 50/50 obsoleto | **P0 — Control de cambios** | Propuesta 30/70 nueva y auditada, #54 queda marcada como histórica |
| B05 | Cambio de flujo: aceptar antes de generar enlace desde panel | **P0 — Producto y seguridad** | Diseño de estados y prueba de fallo/conciliación; sin enlace en presupuesto |
| B06 | Stripe Connect no existe con cuentas Rafa reales | **P1** | Onboarding, configuración, permisos, webhook con `event.account`, prueba TEST autorizada y reconciliada |
| B07 | G06 términos, desistimiento, devoluciones, protección de datos | **P1** | Validación contractual con Rafa, responsable de pagos y RGPD |
| B08 | Falta métrica agregada de uso para monetizar FIFO | **P0 S02** | Informe de demanda sin PII, modelos económicos, precio/entitlement decididos antes de preparar 01/01 |
| B09 | No existe control de descarga pagada S02 | **P0 S02** | Entitlement de pago protegido en backend y todas las rutas de entrega/archivos alternativos |
| B10 | Integración de múltiples PR + migración/rollback | **P0 liberación** | Matriz de dependencias, diff total, revisión independiente, respaldo verificable y ensayos end-to-end |

## 6. Plan de entregas por gates (sin fecha ficticia ni despliegue automático)

**Gate 0 — Alinear negocio:** resolver B01/B02/B05/B07 de S01; alcance/cupos de S02; nombrar responsables y registrar decisiones. Nadie programa integraciones de pago hasta aprobar estas especificaciones.

**Gate 1 — Inventario integrado:** comparar `main`, PR por rama, migraciones y estado Railway con permisos de **solo lectura separados**, validar seguridad base sin exponer información; reconstruir dependencias/commit SHA y prueba de bootstrap con copia aislada.

**Gate 2 — S01 Connect arquitectura:** especificar comerciante Rafa, comisión bruta, cargo directo y ajuste de procesamiento **30/70**, reflejar aceptación previa con enlace posterior desde panel, controlar idempotencia/responsabilidad y preparar sandbox sintético.

**Gate 3 — S01 validación:** cerrar contrato G06; consent snapshot/append-only; Stripe TEST real **solo con autorización**; pruebas de duplicados, faltas de ACK, provider outage, refunds/disputas, conciliación y límites de acceso/roles.

**Gate 4 — S02 demanda y precio:** análisis anonimizado histórico y, con autorización distinta, snapshot agregado actual; comparar ticket, costo, frecuencia y estacionalidad. Decidir entitlement, pruebas y facturación propia fuera o dentro de servicio elegido.

**Gate 5 — QA/release separados:** S01 y S02 tienen checklists, credenciales, facturación, webhooks, reembolsos, observabilidad y aprobaciones separados. Fecha 01/01/2027 es requisito de negocio para S02, no permiso automático de deploy.

## 7. Preguntas iniciales con prioridad

1. **Precio S01:** si Rafa pide 200 € por el servicio, ¿debe el cliente pagar **260 €** (Mariano cobra el 30 % de los honorarios de Rafa) o **285,71 €** (Rafa obtiene el 70 % del total y Mariano el 30 %)? Los impuestos se decidirán aparte. El reparto del **coste Stripe 30/70 ya está confirmado**.
2. **Factura S01:** ¿Rafa emitirá factura al cliente por el **importe íntegro que pague en Checkout** o por sus **honorarios**, y cómo se documentará fuera de la app la remuneración de intermediación de Mariano? Rafa/asesor deben validar la estructura antes del cobro.
3. **Confirmación del flujo:** ¿el cliente acepta desde web y solo después Rafa pulsa «Generar/enviar enlace» desde panel, o aceptas que el sistema genere **automáticamente** el enlace tras aceptar, siempre con estado/auditoría? El diseño registrado hasta ahora prioriza el **control por panel**.
4. **Disputas y devoluciones S01:** si el cliente cancela o impugna, ¿Rafa gestionará la relación con él y decidirá la devolución, con visibilidad y aprobación del ajuste a tu comisión? Definir quién paga gastos adicionales.
5. **Acceso profesional S01:** ¿Rafa debe acceder a los documentos fiscales desde la plataforma o preferís que la web gestione solo solicitud/presupuesto/pago y el expediente técnico se trate directamente entre Rafa y cliente por canal privado? Esto cambia la superficie RGPD.
6. **Evolución S01:** ¿la plataforma está diseñada exclusivamente para Rafa o en el futuro incorporará varios asesores? Esto determina la arquitectura Connect de cuentas/roles.
7. **Pago FIFO S02:** ¿se cobra solo al descargar o ya al generar, y qué implica un error/regeneración? ¿Qué ocurre con usuarios anteriores?
8. **Alcance FIFO S02:** ¿un pago debe cubrir informes de todos los exchanges y ejercicios fiscales o estará vinculado a año, exchange/paquete o créditos? No fijar tarifa antes de estadísticas.
9. **Datos para análisis:** ¿autorizas una herramienta **local de solo lectura** sobre el respaldo privado ya existente en Mac (sin enviar filas/PII ni consultar DB actual), que entregue exclusivamente contadores/agregados? El acceso a producción requeriría autorización separada.
10. **Organización de decisiones:** ¿quién aprobará por escrito, con Rafa, tarifas, impuestos, condiciones de devolución y facturación? Nombrar punto de contacto/revisión jurídico-fiscal antes de Live.

## 8. Estado final del documento

**AUDITORÍA ESTÁTICA DEL REPOSITORIO: inventario y mapa preliminar.**  
**AUDITORÍA OPERATIVA DE PRODUCCIÓN: PENDIENTE, NO AUTORIZADA EN ESTA PR.**  
**S01 Stripe Connect Live: NO-GO. S02 descargas pagadas: NO-GO.**  
**No se ha consultado Railway/Stripe/MERU/PayPal ni alterado el código de producción.**


## 9. Actualización funcional confirmada por el propietario — 13/10/2026 (PREVALECE sobre las preguntas y las hipótesis anteriores)

Esta sección recoge las decisiones posteriores a la primera versión de la auditoría y **resuelve** las dudas B01, el reparto de gasto de Stripe, la custodia de documentación del asesoramiento y la dirección de producto. Si hay diferencias con capítulos anteriores, **esta sección tiene prioridad**.

### 9.1. S01 — negocio, condiciones y operación confirmados

| Tema | Decisión del propietario | Implicación para desarrollo |
| --- | --- | --- |
| Comisión Mariano | **30 % DE LOS HONORARIOS fijados por Rafa, añadido a ellos** | Si Rafa fija 200 €, el cliente paga 260 € (antes de concretar impuestos); comisión bruta Mariano 60 €. **NO** es el 30 % del total de 260 €. Cerrar B01 |
| Gastos de procesamiento Stripe | **30 % Mariano / 70 % Rafa del coste realmente cobrado por Stripe en S01** | Para coste ilustrativo 4,15 €, Mariano paga 1,25 € y Rafa 2,90 €; asignar el céntimo residual de redondeo a Mariano. El código 50/50 de PR #54 está OBSOLETO y no debe desplegarse |
| Porcentaje configurable | Mariano quiere variable editable del sistema con aplicación automática | Parámetro único versionado (`commission_rate_bps=3000` inicial), protegido por permisos, cambio auditable, efectivo **solo para futuros presupuestos**. Persistir el % y cálculo en snapshot de cada oferta; sin recálculo retroactivo |
| Prestación profesional | Rafa actúa como autónomo con seguro y atiende al cliente y sus reclamaciones | Plataforma actúa de intermediaria tecnológica; configuración preferida Connect **direct charge** a cuenta de Rafa, sujeto a aprobación contractual, KYC y condiciones del proveedor |
| Facturas | Rafa gestiona su negocio y emite facturas por su cuenta. **La app no las crea, ni dicta cuándo o cómo hacerlo.** | Mantener facturación de asesoría fuera del sistema. La remuneración de intermediación de Mariano **sí** tiene obligaciones fiscales propias que revisar con Rafa, fuera de la app |
| Archivos de Rafa | **La web NO debe almacenar ni intercambiar documentación fiscal profesional** entre Rafa y cliente | Confirmar en Railway que `ENABLE_ADVISORY_UPLOADS` está desactivado, inventariar en solo lectura registros `FiscalAdvisoryFile`/archivos históricos y planificar deshabilitación permanente **sin borrar evidencia legal previa sin revisión**. El código de `main` conserva endpoints activables y tabla; el panel actual indica subidas desactivadas y comunicación externa por email |
| Aceptación y pago | Mariano **permite automatizar** generar/enviar Checkout tras aceptación si es la opción mejor estudiada | Hacer comparación de alternativas (automática vs desde panel) bajo idempotencia/conciliación antes de fijar UX. El bloqueo de pago incierto y el registro de aceptación no deben perderse |
| Escala | Potencial futuro de múltiples asesores | Diseñar abstracción `advisor_id / connected_account_id` y permisos por expediente, aunque solo Rafa se active en V1; no construir marketplace completo prematuramente |
| MERU | El IBAN MERU del propietario ya está dado de alta en su Stripe | Acredita la configuración indicada, **no** payouts abonados ni aceptación garantizada de la cuenta futura de Rafa |
| Porcentaje de ingresos vs costes | **Son bases distintas** y ambas válidas | Honorarios + 30 % para el **ingreso**; 30 % / 70 % del coste de **procesamiento** para el gasto. No intentar hacer que Mariano represente el 30 % del precio final |

### 9.2. S01 — requisitos funcionales actualizados para diseño, NO implementación todavía

1. Usuario solicita asesoramiento, sin adjuntar documentación fiscal a la plataforma.
2. Rafa evalúa y fija precio, alcance y condiciones; el sistema calcula `honorarios × porcentaje/10 000` con redondeo decimal, total, versión de comisión y vigencia. Resolver impuestos aplicables con asesoramiento profesional, no escribir IVA=0 por defecto.
3. Enviar presupuesto y su versión exacta; recibir aceptación explícita con protección CSRF, validación de identidad adecuada, términos y snapshot inmutable. Aceptación `!=` cobro. El enlace de pago nunca se envía con presupuesto no aceptado.
4. **Elegir después de revisar UX y seguridad** si generar enlace de forma automática, o enviar desde panel con confirmación de Rafa; separar transacción de aceptación y reserva durable de Checkout si hay procesamiento diferido, sin aceptar huérfanos irrecuperables, ni segundo cobro. PR #50/#52 solo eran harnesses sintéticos.
5. Crear Checkout **direct charge** en cuenta Connect de Rafa y comisión bruta de la plataforma, y verificar cobro con firma, cuenta Connect y conciliación; no usar el retorno del navegador para marcar `paid`.
6. Rafa trabaja con el cliente directamente, fuera de la plataforma, y gestiona facturas y reclamaciones.
7. Conciliar coste Stripe del cargo real y compensar el **30 % a cargo de Mariano**, con control de saldo y una sola `application_fee_refund` a la cuenta de Rafa, *si se valida en Stripe Test*. No devolver al cliente esa compensación contable. Refunds al cliente y disputas necesitan su propio protocolo.
8. Los registros administrativos mínimos (solicitud, presupuesto, aceptación y pago) sí se conservan para trazabilidad; «no almacenar nada» aplica a **documentación del trabajo fiscal**, no a los metadatos estrictamente necesarios para operar la web.

### 9.3. S02 — principio comercial y análisis antes del paywall

- Objetivo confirmado: **a partir del 01/01/2027 todos los usuarios deben pagar para descargar un FIFO completo y utilizable para presentar sus impuestos**. No decidir todavía anual, mensual o crédito por informe sin analizar uso real.
- El usuario considera viable un **modelo de demostración/captación previo al pago**; priorizar una vista previa *honesta, claramente etiquetada como demo y no apta para presentar*, por ejemplo verificación de compatibilidad de CSV, cobertura/exchanges, datos de calidad, procesamiento y explicaciones sin entregar un resultado fiscal reconstruible. **No alterar ni falsear importes** para hacer un «informe incorrecto a propósito».
- Hay **dos segmentos presuntos**, usuarios particulares y posiblemente despachos/profesionales con muchos informes. El volumen alto es una *señal*, no evidencia de profesión: analizar percentiles, informes/exchanges/años por usuario anonimizado, recurrencia, cohortes, errores, reutilización y coste computacional. Si aparece un segmento profesional, diseñar derecho y precio específico con condiciones de uso y licencias.
- El servidor ha de exigir entitlement pagado en **todas las vías de descarga/obtención del informe completo**, no solo ocultar un botón; proteger tokens temporales y endpoints de datos equivalentes. Resolver reintentos de un mismo reporte, errores, soporte y no penalizar correcciones técnicas.
- Modelo 721 y herramientas adicionales: decidir inclusión después del análisis para evitar regalar indirectamente un informe fiscal completo si el producto es de pago.
- **Prioridad de datos:** utilizar primero respaldo local aislado (solo consultas SELECT/agrupaciones y sin PII exportada); la revisión de estadísticas actuales de producción necesitará aprobación específica de acceso READ ONLY, diferente a realizar compras o configuraciones.

### 9.4. Programa de rediseño UX/UI — cuándo ejecutarlo

El propietario ya tiene **auditoría visual y prompt para Codex** para un estilo más limpio inspirado en principios de Apple. **No repetir la auditoría ni reescribir el prompt sin necesidad.**

**Decisión recomendada: iniciar el diseño de base AHORA en una rama aislada, pero NO realizar inmediatamente un rediseño transversal ni desplegarlo.**

| Momento | Alcance seguro | Requisito previo para integrar |
| --- | --- | --- |
| **Ya, en paralelo a auditoría/decisiones** | Inventario de páginas, tokens visuales, tipografía, espaciado, componentes responsive, menú/accesibilidad y prototipos. Crear rama propia desde SHA controlado. No tocar páginas financieras inestables. | Usar la auditoría y prompt ya preparados, sin cambiar secretos/DB/endpoints; comprobar que no se solapan archivos con PR de seguridad |
| **Tras congelar reglas de flujo y mapa de páginas** | Home, Cómo funciona, FAQ y páginas públicas no financieras; sistema de componentes y pruebas visuales 320/375/768/1024/1440 px; navegación/SEO/performance. | Pruebas E2E de formularios existentes, responsive/AA y regresiones; revisión staging, despliegue solo con autorización |
| **Tras definir arquitectura S01 Connect y S02 paywall** | Pantallas de solicitud, presupuesto/aceptación, Checkout y panel Rafa; vista previa FIFO y planes/entitlement S02 | Estados/backend y textos finales congelados, protección financiera intacta; pruebas UX de pago erróneo, expirado y recuperación |
| **Antes de apertura S02 de enero 2027** | QA completo de compra y descarga de FIFO; avisos de precio/ayuda, analítica sin PII, operación soporte y verificación de todas las rutas | Sin permitir acceso PDF completo gratis por URL o API alternativa; GO de producto, legal, fiscal, seguridad y rollback separado de S01 |

Evitar una única PR gigantesca: separar tokens/diseño base, páginas públicas y pantallas transaccionales. **No fusionar ni desplegar el rediseño** en medio de migraciones de seguridad, y no cambiar la UX de pagos hasta estabilizar contratos y máquinas de estados. En especial, no mezclar rediseño y cambio de backend en una misma PR.

### 9.5. Preguntas realmente pendientes (no volver a preguntar lo ya contestado)

- **Contrato S01:** Rafa y Mariano deben confirmar por escrito responsabilidades de merchant-of-record, aceptación contractual, fiscalidad sobre honorarios/30 %, reversión de comisión, disputas/chargebacks y tratamiento de la remuneración propia de Mariano. No corresponde a la app decidir facturas de Rafa.
- **Opcional:** automatización de enlace inmediatamente después de la aceptación o con aprobación desde panel, tras estudio de riesgos/conversión.
- **S02:** analizar datos históricos de uso, tarifas y eventual licencia profesional antes de elegir tipo/importe de plan; decidir formalmente alcance del Modelo 721.
- **Operación:** autorización independiente y limitada para contraste de configuración real y para cualquier prueba Stripe Test externa. Sin cambiar pagos reales ni producción.

**Resultado de esta actualización: S01 variables y reglas económicas documentadas, custodia documental y rediseño UX posicionados, hipótesis S02 de particulares/profesionales identificada. Quedan pendientes análisis de datos y contrato jurídico. No hay GO para merge/deploy/cobros.**
