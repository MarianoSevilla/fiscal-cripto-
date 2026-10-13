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
