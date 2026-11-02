# SEC5-PRIV — Laboratorio de restauración y conciliación PostgreSQL 18

**Estado:** PR experimental con datos ficticios; no es un procedimiento operativo ni una migración. **Fecha:** 02/11/2026.

## Riesgo demostrado por el diseño previo

Una referencia de supresión o bloqueo conservada exclusivamente **dentro de la propia base PostgreSQL** se pierde si se restaura una copia más antigua. Un `pg_restore` correcto no demuestra que los datos previamente retirados sigan inaccesibles. El sistema restaurado debe permanecer **sin tráfico** hasta terminar una reconciliación confiable y acreditada.

## Qué ejecuta la CI

1. Verifica un entorno GitHub Actions desechable con PostgreSQL 18, sin `DATABASE_URL`, configuración Railway ni claves de Stripe, Gmail o Resend. El script se encuentra **solo en tests** y no está conectado al arranque de Flask.
2. Crea una base separada con las **17 tablas ORM** de la aplicación y tres errores CSV con datos ficticios. Dos pertenecen a A; el tercero pertenece a B pero contiene un correo copiado de A para probar que el email por sí solo no determina titularidad.
3. Obtiene un backup real mediante el cliente **`pg_dump`** de `postgres:18` ejecutado en Docker en el runner de CI. Conserva los bytes solo en memoria del proceso, fuera del repositorio.
4. Simula la decisión posterior al respaldo de bloquear uno de los errores y suprimir otro. El **registro de decisiones fuera de la copia** contiene identificadores, tipo de decisión, secuencia y huellas HMAC de filas, sin datos personales en claro. El manifiesto se firma con otra operación HMAC; la clave es ficticia y está fija **únicamente en este ensayo**.
5. Destruye y recrea **solo** la base desechable de CI y ejecuta **`pg_restore`** sobre los bytes anteriores a las decisiones. Comprueba que las filas han reaparecido, pero que el comprobador preapertura rechaza la restauración todavía no reconciliada.
6. Comprueba rechazo ante manifiesto faltante, firma manipulada, copia incorrecta, secuencia incompleta, sujeto ajeno incluso con manifiesto firmado y fila restaurada diferente de la revisada.
7. Ejecuta un fallo inyectado después de la primera eliminación/reubicación: PostgreSQL debe revertir **tanto el DDL como los cambios de datos**; ninguna marca de reconciliación puede quedar válida.
8. Repite el proceso correctamente en una transacción: traslada el registro de bloqueo simulado a un esquema reservado, elimina el suprimible sin conservar su contenido, inserta recibo de reconciliación y prueba idempotencia del segundo intento.
9. Comprueba acceso denegado al esquema reservado desde un login SQL ordinario restringido y lectura excepcional sin modificación. El registro del usuario B permanece intacto. Finalmente elimina base y roles del ensayo.

## Contrato preapertura del laboratorio

- **Faltar cualquier manifiesto, firma o decisión esperada implica NO-GO.**
- **Coincidencia de email nunca autoriza retirar datos de otro usuario.** La huella del registro revisado debe coincidir exactamente con la versión restaurada; cambios no acreditados fuerzan revisión.
- **El hecho de que el backup sea restaurable no es autorización para exponerlo.** Solo el ensayo con el manifiesto validado y el recibo de replay confirmado devuelve una respuesta positiva.
- **No existe automatización de cierre del tráfico real:** este comprobador no está conectado al arranque de la aplicación, al proxy, a Railway ni a Gunicorn. Cualquier restauración real debe mantenerse fuera de servicio mediante medidas operativas independientes hasta implementar y validar su puerta productiva.

## Limitaciones que impiden declararlo solución real

- El archivo de decisiones está representado mediante un manifiesto **sintético en memoria**, no un registro externo duradero e íntegro mantenido durante la operación real. HMAC autentica los eventos recibidos, **pero no demuestra por sí solo que el historial esté completo, sea el último o que no se haya omitido un evento**. En un sistema real habría que acreditar procedencia, completitud y punto de corte, custodiar una clave fuera de backups y evitar replay de versiones antiguas.
- La restauración cubre tablas reales pero **solo dos registros sintéticos de `processing_errors`**; no resuelve todas las finalidades ni los campos libres de las 17 tablas. El esquema reservado y sus credenciales de prueba no son un almacén legal operativo.
- La marca de replay solo demuestra la decisión técnica para estos registros. No equivale a acreditar bloqueo legal conforme al artículo 32 LOPDGDD, supresión integral, cumplimiento RGPD, destrucción posterior o conservación adecuada.
- No se comprueban supresiones ni bloqueos en servicios externos: **Stripe, Gmail y Resend** siguen sujetos a sus propios procedimientos y confirmaciones. La restitución de información financiera puede requerir una evaluación especial.
- No se utilizan **backups privados de producción**, no se cambian credenciales, no se toca Railway, no se modifica el arranque de Flask, no se crean tareas automáticas ni se solicitan permisos de pago.

## Condición para integración

Revisión de código, CI obligatoria 3/3 PASS sobre el **commit exacto** y autorización posterior de fusión. La integración del ensayo no autoriza una recuperación de datos reales. El plan de continuidad productiva y la conciliación confiable de eventos entre copias permanecen pendientes.
