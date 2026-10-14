# S01 — Fase inicial · Contrato económico de presupuestos personalizados

**Estado: PR DRAFT. NO MERGE. NO DEPLOY. NO COBROS.**

Base verificada: `main` `56882073295faae3bd1bc3632288a970acb330da`.
Rama: `feature/stripe-s01-advisory-test`.

## Requisitos comerciales confirmados por el propietario (12/10/2026)

- S01: exclusivamente presupuesto personalizado de declaraciones y asesoramiento fiscal,
  estudiado y valorado individualmente por Rafa.
- Rafa comunica sus **honorarios**. La aplicación calcula un suplemento del **30 %**
  sobre esa base, redondeado una vez a céntimos con HALF_UP.
- Ejemplo: honorarios 200,00 € + comisión 60,00 € = **260,00 €**
  antes de determinar el tratamiento tributario aplicable.
- Un correo al cliente contendrá el presupuesto final y, tras integrar Checkout,
  un enlace privado de pago.
- Procesador elegido: **Stripe Checkout** (tarjeta, Apple Pay y Google Pay).
  No integrar PayPal como nuevo procesador.
- Destino previsto: IBAN EUR de MERU/Banking Circle ya registrado en Stripe;
  **payout efectivo y admisión por MERU todavía no verificados**.
- S02 (suscripciones): totalmente fuera del alcance de este desarrollo.

## Entrega de esta primera iteración

1. `advisory_s01_pricing.py`: importe decimal validado, cálculo inmutable en
   céntimos, comisión bps y redondeo controlado.
2. Modelo y migración aditiva con `rafa_fee_cents`, `commission_cents`
   y `commission_rate_bps`. Nunca backfill automático de importes legacy.
3. El campo de presupuesto introducido por Rafa expresa ahora **honorarios**;
   `quoted_amount` conserva el **total que verá el cliente**.
4. Pruebas puras sin llamadas a Stripe, PayPal, Resend ni PostgreSQL.

**Esta PR no crea sesiones de Stripe Checkout, no modifica el webhook, no activa
cobros ni está lista para fusionar.** El enlace de pago existente y los
endpoints PayPal legacy permanecen en la base original; por eso está prohibido
desplegar esta PR aisladamente. Requiere revisión conjunta con PREFREEZE #30,
PayPal U04 #29 y verificación de firma Stripe #32.

## Bloqueantes para completar S01

- Determinar con Rafa quién presta y factura el servicio al cliente y cómo
  se trata el IVA del componente del 30 % (no asumido en esta iteración).
- Diseñar Checkout Sessions individualizadas con intención durable, clave
  de idempotencia persistida, prevención de doble cobro y conciliación si
  Stripe cobrase y se perdiera la confirmación local.
- Integrar la firma obligatoria del webhook (#32), validar por Stripe el
  importe/moneda/session y autorizar únicamente transiciones idempotentes;
  controlar errores de escritura y deduplicación de eventos.
- Integrar el bloqueo PREFREEZE antes de habilitar cualquier escritura financiera.
- Secuenciar Alembic: #29 introduce otra revisión desde el mismo head actual;
  resolver en rama de integración con un único grafo lineal o merge revision
  revisado. Nunca ejecutar migraciones en producción durante esta PR.
- Tests PostgreSQL 18, seguridad de concurrencia, CI, navegador e integración
  con Stripe **Test** solo tras tener staging preparado y autorización separada.

## Criterios NO-GO

Sin merge, despliegue, cambios en Railway, credenciales, bancos, cuenta Stripe,
activación de métodos, links, webhooks externos, correo real, migraciones en
producción, ni transferencias. El pago real comienza solo tras autorización
expresa del propietario y revisión de los bloqueantes anteriores.
