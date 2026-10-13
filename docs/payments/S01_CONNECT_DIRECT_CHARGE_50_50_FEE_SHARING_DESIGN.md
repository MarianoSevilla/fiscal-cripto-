# S01 — Stripe Connect: cargos directos de Rafa y reparto 50/50 de comisiones (DISEÑO)

**13/10/2026 · PR de laboratorio apilada sobre #53 · SIN merge/despliegue/Stripe API ni fondos reales.**

## 1. Hechos de negocio confirmados

- **Dos negocios, dos modelos de cobro**: S01 refiere clientes a Rafa (autónomo y asegurado) que presta el servicio y emite sus facturas **externamente**; S02 informes FIFO son producto propio de la web y tendrán cobro independiente desde el 1 de enero de 2027, pendiente de análisis estadístico.
- Secuencia S01 real: **solicitud web → valoración personal de Rafa → presupuesto desde panel (honorarios + 30 %) → aceptación expresa del cliente → operador genera/envía enlace de pago desde panel → Stripe verifica cobro → Rafa presta servicio y factura**. Aceptación no equivale a pago. **No** generar automáticamente enlace en el POST de aceptación final; #50/#52 eran un harness ficticio.
- Rafa abrirá sus propias cuentas Stripe y MERU, con titulares de empresa/profesional verificables. **No** dar por supuesto que MERU admite Stripe o un determinado IBAN sin validación expresa de ambas entidades.
- El propietario **quiere compartir las comisiones de procesamiento de Stripe** entre Rafa y Mariano; se propone **50 % para cada uno como hipótesis de diseño todavía pendiente de ratificación expresa**.
- Aunque se describe la web como intermediaria, **el encaje de la facturación, impuestos, cobro y reparto de responsabilidades debe aprobarse con Rafa** antes de crear pagos. No emitir facturas desde la app.

## 2. Arquitectura recomendada a validar con Stripe y Rafa

Para minimizar la recepción y redistribución de dinero ajeno en la cuenta de Mariano, evaluar **Stripe Connect — cargos directos en la cuenta conectada de Rafa**:

| Dimensión Accounts v2 propuesta | Valor | Motivo |
|---|---|---|
| Identidad de comerciante y prestador | Rafa: `configuration.merchant` | Rafa presta el servicio y el cliente paga al profesional |
| Dashboard de la cuenta conectada | Acceso completo `dashboard=full` | Rafa gestiona sus propios pagos, reembolsos y reclamaciones |
| Tarifa de procesamiento | Stripe factura a la cuenta conectada `fees_collector=stripe` | El procesamiento se carga inicialmente a Rafa |
| Saldos negativos en la cuenta conectada | Stripe `losses_collector=stripe`, sujeto a elegibilidad/condiciones | No confundir con responsabilidad de la plataforma por su propia cuenta |
| Patrón de cargo | **Direct charge**, crear Checkout bajo `stripe_account` de Rafa | Cargo y PaymentIntent se registran en la cuenta de Rafa |
| Remuneración de plataforma | `payment_intent_data[application_fee_amount]` (en céntimos) | Una única aplicación fee bruta del 30 %, antes de ajuste de procesamiento |
| Tipo de experiencia | Checkout alojado por Stripe | El enlace se envía DESPUÉS de la aceptación y orden desde panel |

**No crear ni modificar Accounts v2, claves, roles, onboarding o payouts hasta contar con autorización concreta y confirmación de disponibilidad del proveedor.** Configuraciones de responsabilidades pueden ser difíciles de cambiar posteriormente. Las cuentas existentes abiertas por Rafa deben verificarse con las instrucciones de incorporación Connect apropiadas; no asumir que pueden vincularse automáticamente.

Fuente técnica actual: https://docs.stripe.com/connect/accounts-v2/connected-account-configuration y https://docs.stripe.com/connect/direct-charges.md?platform=web&ui=stripe-hosted

## 3. Regla económica candidata: mitad del procesamiento para cada parte

Presupuesto **de laboratorio**, sin decisión fiscal: honorarios Rafa `R=20.000c`, comisión bruta plataforma `C=6.000c`, pago cliente `P=26.000c`. **La tributación y el precio final con IVA/no IVA no se han decidido:** esta muestra no se usa para ofertar al cliente.

Tarifa actual de referencia para tarjeta estándar EEE (España): `1,5 % + 0,25 €`; procesar 260 € arrojaría 4,15 € **solo como estimación**. Otras tarjetas o métodos llevan tarifas distintas. Fuente: https://stripe.com/es/pricing .

### Reparto de 415 céntimos reales ilustrativos

- Rafa soporta procesamiento inicial `F=415c` desde su cuenta conectada.
- La aplicación recibe inicialmente `application_fee_amount=C=6.000c` de la cuenta Rafa; el cobro subyacente corresponde a Rafa.
- Una vez **verificado el pago y recuperado el coste real en la Balance Transaction del cargo DIRECTO**, calcular con céntimos: `aporte_plataforma = redondeo HALF_UP(F * 0,5) = 208c`; `aporte_rafa = F - 208c = 207c`.
- Para compensar a Rafa, **devolver parcialmente 208c de la application fee a su propia cuenta conectada** mediante `POST /v1/application_fees/{id}/refunds` con `amount=208`; **no** hacer una devolución al cliente. Stripe documenta que esta API devuelve fondos a la cuenta de la que se cobró la comisión. Está **POR VALIDAR EN STRIPE TEST** para la configuración concreta. Fuente: https://docs.stripe.com/api/fee_refunds/create
- Neto económico, ignorando IVA y costes adicionales: Rafa `20.000 - 207 = 19.793c` (197,93 €), plataforma `6.000 - 208 = 5.792c` (57,92 €); `19.793 + 5.792 + 415 = 26.000c`.
- Los céntimos impares los soporta la plataforma. Solo se comparte el procesamiento del cargo; **comisiones de Connect, disputas, reembolsos, pagos bancarios, conversión u otros cargos** no deben compensarse automáticamente con esta fórmula sin acuerdo separado. Si la tarifa real supera lo que permite devolver la comisión de aplicación, **bloquear para revisión**, nunca truncar silenciosamente.

**Advertencia contable:** la comisión bruta contractual (60 € en el ejemplo) es diferente de la liquidación neta (57,92 €). La devolución parcial al profesional es una corrección del gasto de procesamiento pactado; Rafa y Mariano deben decidir con su asesor cómo documentarla junto al 30 % y al tratamiento fiscal antes de Live. No genera factura la plataforma.

## 4. Diferenciar cobro confirmado y liquidación de comisiones

No retrasar el servicio de Rafa por una conciliación contable tardía: el criterio para empezar el trabajo debe ser **cobro confirmado y conciliado del cliente**, independientemente de que el reparto de los costes de procesamiento figure `pending` en el panel. En cambio, si no se puede verificar el cobro con webhook firmado + recuperación GET en la cuenta correcta, **NO PRESTAR SERVICIO como 'pagado'** por el retorno del navegador.

Propuesta de estados futuros (NO implementados en esta PR):

- `quote_pending → quote_sent → quote_accepted → payment_link_pending → checkout_creating → checkout_ready`; el enlace lo genera y comunica **personal autorizado en panel** tras aceptación.
- `payment_pending → payment_confirmed` solo por evidencia de Stripe; `failed/refunded/disputed` son transiciones auditables propias.
- Una máquina **independiente** de comisión: `fee_unverified → processing_fee_verified → app_fee_refund_reserved → app_fee_refund_confirmed`; estados `uncertain/requires_manual_reconciliation` bloquean otras compensaciones.
- Persistir de forma privada (DB, no logs públicos): IDs tipados de cuenta Rafa y payment, charge, balance_transaction, application_fee, fee_refund, fee real, tarifa/versión del acuerdo, moneda, refund amount, idempotency key, estado y timestamps UTC. Nunca guardar claves privadas, credenciales, nombre, email o DNI en un hash de oferta.
- **Única compensación por application fee/charge**, idempotencia estable y restricción de unicidad; ante timeout o HTTP ambiguo, consultar objeto y lista de refunds de Stripe antes de reintentar. El hecho de que una llamada devuelva error no prueba que no haya ocurrido.
- **No** usar `balance_transaction.fee` de la application fee de plataforma como si fuera el coste de procesar la tarjeta: recuperar la transacción de **cargo del cliente en la cuenta conectada**, verificar `paid`, moneda, importe, cuenta y recibo; investigar posibles ajustes/refunds.
- Stripe puede aplicar costes de procesamiento diferentes según método, tarjeta, país o divisa. Un estimate no autoriza una compensación definitiva.
- Ante devolución al cliente, reclamación o chargeback **no** suponer que Stripe devuelve las comisiones de procesamiento. Conciliación separada con reglas contractuales aprobadas.
- Los webhooks Connect deben verificar la firma y enlazar `event.account` con la cuenta de Rafa y el expediente antes de cualquier transición. No reutilizar ingenuamente handlers webhooks sintéticos de S01. Los eventos pueden duplicarse o llegar fuera de orden.

## 5. Entregables de ESTA PR

- `advisory_s01_connect_fee_split_offline.py`: cálculo **puro** 50/50 a partir de céntimos de coste real suministrados por fixture, devuelve reparto y **propuesta** de devolución parcial de application fee. No importa Stripe, Flask, SQLAlchemy ni servicios externos.
- `tests/test_s01_connect_fee_split_offline.py`: redondeo, costes cero/pares/impares, 4 tarifas ficticias, protección de desbordes, conservación del dinero y tipos inválidos.
- Este documento: arquitectura y riesgos; sin migración, endpoints, cuentas, API calls, cambios en la web, emails o MERU.

## 6. Decisiones antes de desarrollar Connect Test externo

**A confirmar entre Rafa, Mariano y asesoría fiscal/contractual:**

1. Confirmar reparto **50 % y 50 % de la comisión de procesamiento real**; tratamiento de céntimo impar; determinar si hay importe mínimo de plataforma o coste extraordinario.
2. Aprobar descripción jurídica/fiscal del 30 % y del precio final, impuestos, prestador y merchant of record, quién factura qué, y tratamiento del coste de Stripe compensado mediante devolución de application fee.
3. Acuerdo de cancelaciones/retrocesos/disputas/servicio no prestado y quién asume comisiones no reembolsables.
4. Alta, disponibilidad, KYC, condiciones Connect y pagos directos a Rafa; comprobar si sus cuentas Stripe y MERU pueden servir legal/técnicamente para retirar fondos.
5. Acordar cómo administrar una devolución parcial de application fee automáticamente y auditarla; **primera prueba externa exclusivamente en Stripe TEST con nueva autorización específica**.

**G06 comercial y fiscal: NO-GO. G07/G08 públicamente: NO-GO. Connect Test externo: NO-GO. Live: NO-GO.**

S02 queda separado: la web vende acceso FIFO a su propio nombre; jamás asociar un pago S02 a la cuenta conectada de Rafa.
