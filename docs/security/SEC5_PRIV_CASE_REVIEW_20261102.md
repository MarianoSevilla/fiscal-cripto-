# SEC5-PRIV — Contrato de decisiones por expediente (diseño)

**Fecha:** 02/11/2026. **Estado:** diseño y aceptación sintética, sin aplicación a datos reales.
Esta entrega no aprueba plazos de conservación, no ejecuta el artículo 32 LOPDGDD y no implementa borrado, almacén reservado, migraciones, tareas programadas ni endpoints.

## Objetivo y límites

Resolver cada solicitud mediante una **decisión motivada por finalidad**, no mediante un borrado global por antigüedad. La desactivación de una cuenta y la supresión íntegra de todos sus datos son procedimientos diferentes. Los hitos internos de revisión (24 meses de inactividad; 30/90/180 días para ciertas categorías) **no** son vencimientos legales automáticos: 24 meses sin inicio de sesión **nunca** cierran ni eliminan cuentas.

Fuentes técnicas ya existentes:
- PR #172: inventario sintético de 17 tablas ORM, incluidos campos por `user_id`, autores y correos copiados; la coincidencia de email no acredita titularidad.
- PR #173: ensayo PostgreSQL 18 de separación SQL de datos ficticios y rollback; no existe almacén de bloqueo legal real.
- PR #177: contrato de privilegios mínimos y verificación aislada de staging. El rol limitado de producción se contrastó por separado.
- PR #179: la documentación distingue el superusuario histórico del rol operativo posterior.

## Resultado de cada revisión (una decisión por grupo y finalidad)

| Decisión | Regla mínima |
| --- | --- |
| `SUPRIMIR` | Finalidad extinguida, sin obligación aplicable de conservar, identidad y registros atribuidos con certeza y operación técnicamente segura |
| `MANTENER_OPERATIVO` | Finalidad actual demostrada: servicio en curso, derecho adquirido, soporte abierto, obligaciones o incidencias de pago que requieran acceso ordinario |
| `BLOQUEAR_ART32` | Procedencia jurídica revisada; el dato se retira de todas las rutas ordinarias y se reserva bajo credencial SQL independiente, con acceso excepcional restringido y revisión de prescripción |
| `REVISION_ESPECIAL` | Identidad incierta, referencias cruzadas, estado financiero no resuelto, datos de terceros, faltan pruebas o falla un proveedor |

La decisión `BLOQUEAR_ART32` en un expediente **no significa que ya exista el almacén**; nunca equivale a ejecutar un traslado. Una solución de copia segura solo puede valorarse en los supuestos permitidos por el artículo 32 y debe garantizar autenticidad, fecha y no manipulación.

## Ficha mínima de autorización futura

Toda propuesta por expediente documentará de forma minimizada: referencia interna y fecha UTC; acreditación proporcionada de identidad; inventario por tabla/campo de las 17 ORM y fuentes externas; distinción de vinculación por ID, actuación como empleado/autor y coincidencias de correo **candidatas**; finalidad, obligación concreta y revisión prevista; estado de pagos, reembolsos, disputas y claves S01; decisión por grupo con responsable y motivo; incertidumbres sobre Gmail/Resend/Stripe y expedientes del profesional independiente; fecha y custodia de respaldos, más conciliación exigible si se restaura una copia anterior.

No copiar documentación fiscal, contraseñas ni datos personales al repositorio, CI o a informes de auditoría. La ficha no autoriza por sí sola ninguna operación.

## Puertas de aceptación secuenciales

1. **Identidad y ámbito:** verificación suficiente antes de desidentificar; en cuentas ya desactivadas, exigir corroboración externa y mantener las coincidencias de email solo como candidatas.
2. **Fundamento y finalidad:** decisión individual motivada y revisión por caso, sin programar supresiones basadas solo en edad de registros.
3. **Integridad:** respetar referencias por ID, historial de consentimiento, roles de autor, solicitudes de asesoramiento, intentos Stripe, eventos y outbox; nunca borrar datos de otra persona ni romper idempotencia financiera.
4. **Aislamiento:** ensayo con logins reales sintéticos PostgreSQL 18 de privilegios separados; comprobar rutas ordinarias Flask, panel, exportaciones, APIs y tareas. Un booleano `blocked` es insuficiente.
5. **Transacción, recuperación y terceros:** rollback completo ante fallo, reintentos idempotentes, estado externo parcial explícito, y reconciliación de actuaciones posteriores a la copia antes de reabrir una restauración.
6. **Autorización productiva:** revisión independiente de pruebas y criterios por finalidad, backup reciente restaurable y autorización específica de migración, permisos y manipulación real.

Si falta evidencia en cualquier puerta: **no ejecutar**, registrar `REVISION_ESPECIAL` y no declarar supresión completa.

## Casos adversariales de aceptación

El contrato estructurado asociado `SEC5_PRIV_CASE_REVIEW_CONTRACT_20261102.json` enumera casos verificables de: email histórico compartido, cuenta desactivada, referencias S01 y reembolso incierto, bloqueo SQL inaccesible al rol web, fallo transaccional, restauración anterior a la supresión y fallo de proveedor externo. Los resultados esperados son **solo requisitos de futuras pruebas**, no efectos reales. Las pruebas estáticas `test_sec5_priv_case_review_contract.py` preservan esta condición y el conjunto mínimo de escenarios.

**No-go de fase:** aún no hay decisión legal por expediente, sistema real de bloqueo, control operativo de todos los accesos, ni reconciliación de backups implementada. **Ningún cambio productivo queda autorizado mediante esta PR.**
