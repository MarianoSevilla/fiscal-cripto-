# S01 — AUD-001, carrera PG18 entre reemisión y reserva Checkout

**13/10/2026. DRAFT · NO MERGE · NO DEPLOY · NO COBROS · NO CAMBIOS EXTERNOS.**

## Objeto y encadenamiento

Nueva rama \`test/s01-aud001-pg18-quote-checkout-race\`, derivada del SHA inalterado de PR #43: \`93e3abf6a96217630805bebc1560ceccc5aa757b\`. La PR final debe usar la rama de PR #43 como base, y su diff debe limitarse a un test aislado PG18, un paso adicional de Required CI y este documento. Las PR #41, #42 y #43, y \`main\`, permanecen intactas.

## Diseño del ensayo

\`fiscal_app_export/tests/qa_s01_quote_reservation_pg18.py\` crea una base temporal nueva en el PostgreSQL 18 de GitHub Actions. Exige simultáneamente \`GITHUB_ACTIONS=true\`, \`CI=true\` y \`FLASK_ENV=testing\`, y solo utiliza localhost, nombre de base fijo y credenciales ficticias de CI. No lee \`DATABASE_URL\`, Railway ni una copia de producción.

Cada escenario arranca **dos procesos Python** con conexiones PG independientes y \`SELECT FOR UPDATE\` real:

1. **Reemisión primero**: el handler verdadero \`advisory_enviar_presupuesto\` toma el bloqueo y espera; una reserva con el token antiguo intenta bloquear la misma fila. Al liberar el bloqueo, la reemisión termina con HTTP 200, genera un nuevo token y cambia 260,00 € a 299,00 €; la reserva debe rechazarse sin crear intentos. Histórico y auditoría: exactamente una entrada nueva cada uno.
2. **Reserva primero**: \`_reserve\` toma el bloqueo y espera; el handler intenta reemitir el presupuesto. Al liberar el bloqueo, la reserva crea un único intento \`creating\` para el importe y token originales; la reemisión devuelve HTTP 409, sin cambiar presupuesto, token ni historial ni enviar correo.

Ambos escenarios se ejecutan dos veces con nuevos expedientes ficticios. Instrumentación SQLAlchemy antes y después del \`SELECT FOR UPDATE\` confirma que el segundo proceso llega al bloqueo **sin adquirirlo** mientras el primero conserva su transacción. Se comprueba el estado persistido con una sesión PostgreSQL posterior, además de las respuestas.

Solo para probar el cuerpo real del handler sin pasar por la ruta pública PREFREEZE 503, el ensayo compila su función AST sin decoradores dentro de un Flask temporal y usa un stub de correo que **nunca envía mensajes**. Un assert comprueba que el código original sigue decorado con PREFREEZE. La reserva llama al orquestador de TEST, sin ejecutar proveedor Stripe alguno.

## Limitaciones y siguientes puertas

Este control acredita contención transaccional en PostgreSQL 18 efímero, **no** conciliación con Stripe/PayPal, deserialización real del SDK, restauración productiva, rutas HTTP públicas, email real, outbox dispatcher, refunds/disputes, ni ausencia de errores de producción.

La auditoría preintegración permanece **NO-GO**. La prueba de migración sobre copia productiva restaurada requiere autorización, ámbito seguro y procedimiento de eliminación/retención específicos. No realizarla con los datos ni conexiones de producción ni inferir que la CI sintética equivale a ese ensayo.
