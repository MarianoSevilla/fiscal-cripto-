# S01 · G06 — Contrato comercial pendiente y evidencia versionada de aceptación (fase preparatoria)

**Fecha:** 13/10/2026. **Estado: DOCUMENTACIÓN + CONTRATO SINTÉTICO PURO — NO-GO contractual y financiero.**  
**Base:** PR #52, SHA `e2953d113cb3b180ef3bcb502805e605c367beea`, apilado sobre #51/#50/#49.  
**Prohibido:** merge, despliegue, Railway, credenciales, Stripe Test/Live externo, PayPal, MERU, webhooks, migraciones, pagos reales, facturas en la app.

## 1. Decisiones existentes y restricciones vinculantes

| Tema | Confirmación disponible | Qué NO debe concluirse |
| --- | --- | --- |
| Servicio S01 | Asesoramiento fiscal y declaraciones con **presupuesto personalizado**; Rafa estudia cada caso y fija sus honorarios | No es una tarifa fija ni suscripción S02 |
| Desglose económico | Honorarios de Rafa + suplemento **30 %**, redondeado una vez (HALF_UP) en céntimos; en pruebas 200 € + 60 € = 260 € **antes de establecer impuestos** | No implica que 260 € sea el precio fiscal final ni que el suplemento deba anunciarse jurídicamente como una «comisión» |
| Prestación y trato al cliente | Rafa presta la asesoría, trata directamente con el cliente y se ocupa de emitir/enviar las facturas **fuera de la web** | No determina por sí solo quién actúa legalmente como vendedor/merchant-of-record de todo el importe |
| Cobro proyectado | Cliente abonaría total mediante Stripe Checkout; fondos previstos hacia MERU; liquidación posterior a Rafa | No confirma contrato de adquirencia, reparto, admisión de pagos de terceros por MERU ni encaje fiscal |
| PayPal | El propietario declaró que nunca cobró por PayPal en la web; inventario de copia 10/10/2026 con 6 expedientes, cero señales PayPal | No hay motivo para exigir descarga masiva del historial privado como condición inicial; una anomalía concreta reabriría su revisión |
| Desarrollo técnico | PR #52 corrigió AUD-001/002: aceptación+intento en mismo COMMIT; CI #75 1.482 passed, 63 skipped, sin xfails; PG18 dos procesos PASS | No equivale a aceptación legal, autorización Stripe real o despliegue |

**Cualquier texto comercial definitivo requiere revisión y validación por los responsables contractuales antes de presentarse al cliente.** El código de esta PR **no contiene una política legal supuestamente aprobada**.

## 2. Registro de decisiones abiertas — G06 NO-GO

| ID | Decisión obligatoria | Evidencia/autoridad necesaria | Estado |
| --- | --- | --- | --- |
| G06-D01 | Quién contrata y vende el servicio al cliente (identidad legal y domicilio del empresario, responsabilidades) | Acuerdo confirmado entre propietario y Rafa y revisión de asesor jurídico/fiscal | **SIN DECIDIR** |
| G06-D02 | Identidad exacta del prestador y del emisor de factura, y cómo se documenta un eventual cobro por cuenta de otro | Acuerdo escrito, comprobación de facturación y derechos del cliente | **SIN DECIDIR**; se mantiene que Rafa genera facturas fuera de la app |
| G06-D03 | Tributación del servicio, tratamiento IVA de los honorarios y del suplemento del 30 %, base imponible, retenciones si aplican y precio final **impuestos incluidos** | Criterio fiscal de Rafa/documentación justificativa | **SIN DECIDIR**; nunca asignar IVA=0 por defecto |
| G06-D04 | Cómo se articula el flujo de recepción del total en Stripe → MERU → liquidación Rafa; obligaciones del titular de la cuenta y admisión bancaria | Revisión contractual de proveedores y responsable de pagos | **SIN DECIDIR** |
| G06-D05 | Alcance preciso del presupuesto, trabajos incluidos/excluidos, plazos, documentación requerida, quién responde ante incidencias | Texto aprobado por Rafa y propietario | **SIN DECIDIR** |
| G06-D06 | Condiciones de cancelación, reembolso y chargeback, canal reclamaciones, responsable de devolución | Política aprobada coherente con reglas consumidor y procesador | **SIN DECIDIR** |
| G06-D07 | Información sobre desistimiento y, **por separado**, solicitud voluntaria de inicio anticipado del servicio y consecuencias al completarse | Revisión jurídica específica del tipo de contrato/cliente | **SIN DECIDIR**; no presumir renuncia al derecho por pagar |
| G06-D08 | Condiciones generales versionadas, datos identificativos visibles, idioma, confirmación contractual en soporte duradero, prueba de identidad y retención proporcionada | Aprobación legal/privacidad y diseño de UX | **SIN DECIDIR** |

Mientras exista alguna decisión relevante sin resolver, **ningún enlace público de pago o formulario de aceptación real** debe activarse.

## 3. Normativa orientativa (no sustituye revisión jurídica)

- **LSSI-CE, Ley 34/2002**, arts. 10, 27 y 28: datos accesibles del prestador; información previa sobre procedimiento de contratación y condiciones reproducibles; confirmación de la aceptación. Texto consolidado: https://www.boe.es/buscar/act.php?id=BOE-A-2002-13758
- **TRLGDCU, Real Decreto Legislativo 1/2007**, arts. 97 y 98: información precontractual, características principales del servicio, identidad del empresario, **precio total incluidos impuestos** y confirmación inequívoca de obligación de pago; cuando procede, confirmación del contrato en soporte duradero. Texto consolidado: https://www.boe.es/buscar/act.php?id=BOE-A-2007-20555
- Artículos 102 y 103: derecho de desistimiento y excepciones para servicios bajo condiciones legales concretas. **Aceptar un presupuesto no equivale por sí solo a perder ese derecho**; las opciones de iniciar el servicio anticipadamente y reconocer sus efectos se deben diseñar por separado cuando proceda.
- Protección de datos: no almacenar documentos fiscales, correos ni IPs indiscriminadamente en el hash o en logs; definir finalidad, acceso restringido, plazos y base jurídica con revisión RGPD antes de retención real.

## 4. Prototipo técnico entregado — sin contratos reales

`fiscal_app_export/advisory_s01_g06_synthetic_contract.py` contiene exclusivamente dos dataclasses **inmutables y congeladas**:

- `S01G06SyntheticOffer`: identificador de expediente ficticio; referencia/fecha de oferta; honorarios, suplemento del 30 %, tributos **introducidos explícitamente** y total EUR; alcance, identidad contractual, profesional prestador, responsable de facturación, explicación fiscal; versión y contenido completo de términos, desistimiento y cancelaciones; referencias *distintas* de aprobación comercial y legal. No hay valores por defecto para ninguna decisión fiscal o legal.
- `S01G06SyntheticAcceptance`: huella del contenido de la oferta, versión de términos, referencia y total mostrado, confirmación expresa y de obligación de pago, timestamp dentro de vigencia, referencia opaca del actor, y decisiones **separadas** de inicio anticipado/desistimiento. No incluye email, DNI, IBAN o token bearer.
- `synthetic_offer_digest`: JSON canónico UTF-8 con claves ordenadas y prefijo de dominio `s01-g06-synthetic-v1` para SHA-256 reproducible. Modificar importe, IVA simulado, contratante, servicio, versión, desistimiento, cancelación o referencias de aprobación invalida cualquier aceptación anterior.
- `verify_synthetic_acceptance`: valida íntegramente huella, tiempo, precio, consentimiento explícito, actor (referencia), y opciones de desistimiento; **nunca** deja pasar `False`, enteros usados como booleanos, placeholders («pendiente», «sin determinar»), tipos erróneos o aprobaciones ausentes. El ejemplo de tests contiene **identidades e impuestos deliberadamente ficticios**.

### Limitaciones técnicas que impiden GO

Un SHA-256 **no es una firma electrónica, no prueba la identidad ni demuestra por sí solo la información realmente mostrada al usuario**. Las referencias de aprobación son entradas, **no verifican la firma** ni la autoridad de quien aprueba. En esta PR:

1. **No se conecta al flujo PR #52**, ni se crea tabla/versión Alembic, ni se incluye el hash en Checkout ni existe formulario cliente.
2. **No se almacena el contrato en BD o soporte duradero**; todavía no hay prueba de acuse enviada por email o canal equivalente.
3. **No se habilita ninguna liquidación, factura, cobro ni solicitud de aceptación Live**, aunque todas las pruebas pasen.
4. Los datos de ejemplo no sirven como términos oficiales. Toda oferta deberá generarse **después** de aprobar G06-D01–D08 y someter el diseño de almacenamiento, acceso, integridad, retención y reconciliación a revisión de seguridad/privacidad.

## 5. Futuro esquema de persistencia (NO IMPLEMENTAR SIN APROBACIÓN)

Una PR posterior podría añadir una entidad aditiva tipo `s01_advisory_consent_evidence`, con **una evidencia inmutable por versión de presupuesto/aceptación**:

```text
advisory_id / offer_reference / terms_version / offer_sha256
price breakdown y total fiscal final (céntimos EUR)
contracting_party_ref / verified_actor_ref (acceso restringido)
accepted_at_utc / explicit_payment_obligation / optional_early_start_flags
legal_business_signoff_refs / durable_confirmation_ref / retention_policy_ref
```

Revisar campos, cifrado/restricciones, esquema de borrado y minimización antes de crear tabla. La oferta y la prueba de aceptación deben vincularse a `S01StripeCheckoutAttempt` bajo un **COMMIT único**, pero no se modifica la transacción PR #52 sin definir antes el contrato real. La transacción nunca confirmará un `paid_at` ni emitirá factura.

## 6. Validaciones y salida de esta etapa

- Pruebas puras y sintéticas: versionado SHA, cambios de cualquier campo y precio, IVA faltante/erróneo, ventanas de tiempo, ausencia de aprobaciones, consentimiento explícito, discrepancia de importe y desistimiento.
- CI requerida completa sobre SHA exacto (backend/PG18/navegación).
- La PR quedará **en borrador y apilada sobre #52**, con diff limitado al prototipo puro, tests y documento.
- Estado G06: **ESPECIFICACIÓN/VALIDACIONES DE LABORATORIO PREPARADAS**, **contrato comercial y consentimiento operativo NO-GO**. Próximo trabajo seguro: recopilar/validar D01–D08 y diseñar la futura evidencia persistida, **sin pedir al propietario repetir datos ya confirmados**.

## 7. Política de liberación

No fusionar, desplegar, migrar, desactivar PREFREEZE, modificar cuentas/variables, crear Checkout/PaymentIntent real o Test externo, ni transferir fondos. **La aplicación no emite facturas**; Rafa las gestiona externamente. S02 (suscripciones) queda fuera de alcance.
