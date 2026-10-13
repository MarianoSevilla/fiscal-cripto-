# S01 — C1: suspensión temporal de presupuestos y cobros

**Aprobación del propietario:** 13/10/2026. **Implementación candidata, aislada y sin despliegue.**

## Alcance autorizado

- Mantener formulario de solicitud, recepción y consulta de expedientes.
- Conservar consulta/listado, notas internas y cambios **no financieros** entre estados
  `submitted`, `pendiente_info`, `under_review` y `waiting_user_info`.
- Suspender envío y reemisión de presupuestos, mensajes externos, aceptación con
  efectos de cobro, enlaces de pago, inicio/captura de PayPal y webhook financiero.
- Conservar el historial PayPal/Stripe y bloquear cualquier cambio de estado de
  expediente con evidencia económica, incluso si su estado parece administrativo.
- No crear facturas. No modificar precios históricos, migraciones ni base de datos.

## Diseño de mínimos: rutas nuevas, no deshielo de las anteriores

Las rutas históricas de presupuesto, mensaje, nota, estado, is-test y borrado
continúan bajo PREFREEZE. Las nuevas rutas `/gestion/nota`,
`/gestion/estado` y `/gestion-token` son exclusivas de asesor fiscal/admin,
con CSRF ligado al usuario/sesión, misma procedencia cuando se declara Origin,
límite de tasa y sin llamadas a email/proveedores.

La ruta de estado admite solo transiciones entre cuatro estados de revisión;
cualquier presupuesto, orden/captura, enlace/token, pago, aceptación o intento
Checkout existente bloquea cambios. Se usa bloqueo de fila en PostgreSQL.
Las notas no modifican estado ni importes, y no disparan email.

El panel elimina las acciones de presupuesto, reenvío de enlace y mensaje
exterior; muestra la suspensión y permite solo notas y estados seguros.
Las marcas de test y el borrado quedan deshabilitados en el panel y siguen
bloqueados en API. Las solicitudes existentes con historial financiero son
de solo lectura en cuanto al estado.

## Gates y límites

Esta rama se basa en **PR #53** SHA `4b02ebfc0cfe7a7bb20214567db06cb08fa20571`;
contiene dependencias apiladas PR #41–#53 y excluye PR #54 50/50 obsoleta.
La prueba de regresión debe confirmar bloqueo antiguo, permisos, CSRF,
gestión y conservación financiera, además de PG18 y navegación.

**NO-GO:** ningún merge, deploy, Railway, backup/migración productivos,
datos personales, proveedores, pagos, cobros o devoluciones. Esta PR no
autoriza por sí sola activar S01 Live; hay que cerrar el resto de gates.
