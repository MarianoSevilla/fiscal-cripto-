# SEC5-PRIV — Ensayo de supresión aislada de una cuenta sin relaciones

**Fecha:** 05/11/2026 · **Estado:** laboratorio PostgreSQL 18 exclusivo de CI, con **solo datos ficticios**. No implementa supresión de cuentas de clientes ni bloqueo legal conforme al artículo 32 LOPDGDD. No fusionar ni desplegar sin revisión y autorización separadas.

## Situación real y objetivo acotado

La ruta `POST /api/delete-account` verifica contraseña o token OAuth y desactiva/desidentifica la cuenta; **no** elimina sus referencias en las otras tablas. Los criterios aprobados el 02/11 son momentos de revisión, no órdenes de eliminación. Las 17 tablas ya cuentan con inventario y los ensayos de `processing_errors` disponen de rollback, aislamiento SQL y concurrencia. En este paso **no se modifica ninguna ruta** ni el comportamiento público.

Se añade una prueba al laboratorio existente `fiscal_app_export/tests/qa_sec5_priv_record_lifecycle_pg18.py` para conocer el alcance real de una operación de supresión de **una fila `users` sin relaciones conocidas**, antes de decidir si merece una futura implementación supervisada.

## Puertas del laboratorio

1. **Entorno:** el mismo guard CI que ya existía: GitHub Actions, `FLASK_ENV=testing`, PostgreSQL 18 desechable de localhost con nombre fijo, `DATABASE_URL` ausente, sin variables Railway ni secretos externos. No se crea CLI, endpoint, migración, permiso, rol ni almacén de producción.
2. **Identidad simulada:** marcador `SYNTHETIC_MANUALLY_REVIEWED`, ID válido, email original aportado y coincidente con una cuenta activa. Este marcador de prueba **no demuestra identidad real**. Se bloquea la fila con `SELECT FOR UPDATE` antes de clasificarla.
3. **Elegibilidad extraordinariamente restrictiva:** solo cuenta `role=user` y `plan=free`. Se rechazan referencias directas por ID, referencias como autor/empleado, cualquier correo coincidente candidato a revisar y referencias indirectas a solicitudes/Stripe, según el inventario sintético de las 17 tablas ya disponible. Se rechaza cualquier cuenta con otros registros, incluso si no hubo pago ni expediente concluido.
4. **Ensayo de cambio:** únicamente para esa fila ficticia sin vínculos conocidos se ejecuta `DELETE` dentro de transacción del laboratorio. Se comprueba rollback de una excepción después del `flush`, reintento sin nueva operación y dos peticiones concurrentes mediante bloqueo de fila.
5. **Aislamiento:** otras cuentas y sus registros de diagnóstico, consultas, campañas o Stripe permanecen. Casos con pagos, cuenta inactiva, identidad errónea, correo histórico coincidente y autor de campaña se rechazan. Los proveedores y los archivos nunca se consultan.

## Interpretación

Una cuenta ficticia sin referencias conocidas puede suprimirse físicamente **en el laboratorio desechable** con integridad de la fila y rollback. Esto **no autoriza** replicar la acción sobre clientes. Aunque todas las referencias conocidas sean cero, no demuestra ausencia de identidad en texto libre de `incidents`, recursos, adjuntos o registros externos. Los correos sin FK siguen siendo **candidatos**, nunca prueba suficiente para borrar datos ajenos.

**No implementa supresión** universal ni bloqueo legal. Tampoco cambia el flujo de baja real, no resuelve conservación de PDF FIFO, compras futuras, reclamaciones, consentimientos, comunicaciones, la custodia del profesional, proveedores, logs o **backups**, ni acredita identidad con un simple ID o correo. En producción, mantener el criterio `REVISION_ESPECIAL` hasta completar evaluación individual por finalidad, custodia y excepciones.

## Pruebas y puerta de integración

El nuevo escenario se ejecuta exclusivamente dentro de la suite PG18 ya registrada en `.github/workflows/required-ci.yml`, sin ampliar workflows. Se añade una prueba estática de que las puertas no se eliminan y de que `app.py` permanece intacto. Deben pasar **backend-tests**, **postgres-bootstrap** y **browser-navigation** sobre el commit exacto. También se exige revisión de diff y de los límites anteriores.

Ningún resultado de CI autoriza migraciones, borrados, creación de roles privilegiados, modificación de proveedores, restauración de copias reales o cambio de política pública. **No fusionar** la PR sin autorización del titular. **No se ha ejecutado ningún borrado real.**
