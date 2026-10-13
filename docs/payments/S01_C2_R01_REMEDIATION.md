# C2-R01 — Remediación C1 en rama aislada (13/10/2026)

**Scope:** C2-01 a C2-05, exclusivamente implementación y pruebas. Base exacta PR #56
`598bb0912ad0dc4521aaba881512b13aa268b4eb`.
Ningún merge, despliegue, proveedor, credencial, migración o dato real.

- C2-01: validador compartido, fail-closed sobre columnas económicas secundarias,
  historial previo y auditoría de presupuesto/servicio, intentos Stripe, órdenes PayPal.
- C2-02: prueba CI PostgreSQL 18 exclusiva, dos procesos, lock FOR UPDATE,
  inserción previa de evidencia bajo mismo lock, no mutación ni proveedor;
  integra paso explícito `postgres-bootstrap`.
- C2-03: indicador `c1_state_editable` de backend en detalle; UI solo refleja ese
  indicador; POST sigue verificando bajo lock y nunca confía en el navegador.
- C2-04: endpoint público de precios S01 responde 503 sin importes y landing
  muestra «Presupuestos suspendidos», sin recuperar tarifas antiguas.
- C2-05: transiciones permitidas solo a `submitted` o `under_review`, ambas
  internas; estados anteriores `pendiente_info` y `waiting_user_info` pueden
  regresar a revisión sin simular comunicaciones. Se mantiene bloqueo de
  mensajes externos.
- C2-06 (privacidad): pendiente de revisión legal separada; no introducir
  consentimientos ficticios o almacenar datos adicionales sin criterio
  jurídico aprobado.

**Invariantes:** PREFREEZE, tombstones PayPal y evidencia histórica se conservan,
sin edición de modelos/Alembic, no generación de links/cobros, FIFO intacto.
Una CI verde NO autoriza integración o despliegue; G04/G05 siguen NO-GO.
