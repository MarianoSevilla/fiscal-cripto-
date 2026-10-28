# 05-C3b · CSV-DIAG-CONSENT-001 — Envío voluntario de archivos fallidos

Estado: PR #155 integrada en main y desplegada; envío público desactivado. Prueba de una sola cuenta preparada en rama aislada y pendiente de integrar.

## Objetivo

Permitir que una persona autenticada cuyo informe FIFO haya fallado comparta **voluntariamente un archivo concreto** para diagnóstico por soporte. El mero error de importación nunca dispara el envío. Se preservan los límites de privacidad de PR #154.

## Comportamiento propuesto

- Una opción adicional aparece después de ciertos errores de análisis solo si `CSV_DIAGNOSTIC_SUPPORT_ENABLED=true`.
- El usuario elige un fichero de su selección local y marca una casilla inicialmente vacía; un botón separado efectúa el envío.
- El servidor exige autenticación, origen permitido, un consentimiento explícito por petición, exchange válido, una sola extensión CSV/XLS/XLSX y tamaño de hasta 8 MiB. Hay un límite inicial de 2 intentos por día y cuenta.
- El servidor no copia deliberadamente el archivo a una tabla ni lo añade a la telemetría existente; `request.close()` intenta cerrar y liberar los archivos multipart (incluido posible spool temporal de Werkzeug) tanto si el envío funciona como si falla; lo transporta mediante la API de Resend exclusivamente a `colab.marianosevilla@gmail.com`, sin destinatario configurable por petición ni entorno. El nombre del adjunto es genérico.
- La respuesta no expone el archivo, claves, dirección de soporte ni detalles de terceros. No se reintenta automáticamente si se desconoce si Resend recibió la solicitud.
- En entornos sin configuración de correo o con el flag desactivado, el envío falla de forma cerrada.

## Prueba de envío limitada a una sola cuenta (pendiente de integración)

- Mantener `CSV_DIAGNOSTIC_SUPPORT_ENABLED=false`: el envío público continúa cerrado.
- Definir **solo para el periodo de prueba** `CSV_DIAGNOSTIC_TEST_EMAIL=<correo exacto de la cuenta registrada que hará el ensayo>`, tras comprobar que existe y que puede iniciar sesión. No usar el correo del buzón de soporte como cuenta de prueba salvo que también sea la cuenta registrada con la que se inicia sesión en marianosevilla.com.
- El servidor coteja el email del usuario **autenticado** con el único email autorizado, sin distinguir mayúsculas; una coincidencia exacta permite el endpoint y muestra el consentimiento en la herramienta. Para el resto de usuarios, el botón no aparece después del error y la API devuelve 404, sin invocar Resend.
- Nunca se envía nada sin consentimiento explícito por petición. Las verificaciones de tipo/tamaño/origen, rate limit y liberación de temporales permanecen inalteradas.
- Efectuar una prueba manual usando **solo un CSV ficticio** con una importación fallida, verificar la recepción en Gmail y el borrado definitivo del correo desde Gmail/Papelera. La respuesta `200` de Resend solo acredita aceptación por el proveedor, no entrega final en Gmail.
- Al finalizar, **vaciar `CSV_DIAGNOSTIC_TEST_EMAIL`** y comprobar el despliegue de restauración. No activar el flag público sin una decisión posterior explícita.
- La restricción requiere una nueva PR y despliegue previamente autorizados; no está vigente en el commit de producción de la PR #155.

## Política de conservación aprobada: opción A — Gmail 30 días

- Destino fijo y exclusivo: `colab.marianosevilla@gmail.com` mediante Resend; el asunto comienza por `[CSV-DIAG]` para distinguir estas incidencias de cualquier correo ordinario.
- **Objetivo máximo de conservación en Gmail: 30 días desde la recepción del correo**. El mensaje y su archivo adjunto se eliminan **antes** cuando termina la revisión del fallo.
- La web no guarda deliberadamente el CSV/Excel en una tabla ni en un directorio propio. `request.close()` libera los recursos multipart, incluidos los temporales de Werkzeug, tras cada petición. Esta limpieza **no** acredita la eliminación de copias en Gmail ni Resend.
- Resend mantiene su propia retención: a fecha 28/10/2026 publica 30 días para datos de correo y logs en planes Free, Pro y Scale; las condiciones y copias técnicas del proveedor son independientes de Gmail. Véase <https://resend.com/security> y <https://resend.com/security/gdpr>.
- **El límite en Gmail es un procedimiento operativo manual, no un borrado automatizado demostrado**. No activar el envío si nadie asume la gestión y verificación de este procedimiento.

### Procedimiento operativo del buzón (antes de activar)

1. Restringir el acceso al buzón al responsable de soporte, con doble factor; no configurar reenvíos automáticos, ni descargar adjuntos si no es necesario. Tratar archivos XLS/XLSX como contenido no fiable: no habilitar macros ni ejecutar adjuntos.
2. Al recibir un mensaje con asunto `[CSV-DIAG]`, anotar la fecha de recepción, identificar la incidencia y revisar únicamente el archivo autorizado. No reenviarlo ni publicarlo; si se descarga para diagnóstico, eliminar la copia local y su papelera al cerrar la investigación.
3. **Al finalizar el análisis**, eliminar el mensaje de Gmail y de la Papelera mediante **Eliminar definitivamente**. Esta acción no borra copias técnicas de los proveedores; tampoco debe interpretarse como garantía de eliminación física inmediata.
4. **Revisión semanal obligatoria:** buscar en Gmail `subject:"[CSV-DIAG]" older_than:21d`, revisar también `in:trash`, y eliminar definitivamente los mensajes de esa clase que alcancen 21 días. Este margen pretende que la gestión normal termine **antes** del día 30, incluso si hay una semana entre revisiones. Si se omiten revisiones, no puede garantizarse el plazo.
5. Verificar periódicamente que no quedan correos de diagnóstico con 30 días o más, incluidos los de Papelera y otros buzones sincronizados; documentar la comprobación sin conservar CSV, nombres originales ni datos de operaciones en un registro adicional.
6. Si no se puede gestionar el buzón, se pierde el control de acceso o falla el procedimiento de borrado, **desactivar `CSV_DIAGNOSTIC_SUPPORT_ENABLED`** y resolver la incidencia antes de admitir nuevos archivos.

Gmail elimina normalmente los mensajes de su Papelera transcurridos 30 días **desde que se envían a la Papelera**, por lo que moverlos a ella al día 30 no satisface un plazo de 30 días desde la recepción. Fuente: <https://support.google.com/mail/answer/7401?hl=es>.

### Límite de las garantías

Este procedimiento no instala un filtro ni automatismo de eliminación en Gmail, no verifica el acceso real al buzón y no puede garantizar borrar todas las copias técnicas de Resend/Google. La política de privacidad y el texto del consentimiento comunican el plazo operativo de Gmail y distinguen el tratamiento de Resend. La comprobación efectiva del borrado depende de la persona responsable; no presentar como técnica o legalmente verificado hasta contar con evidencias operativas.

## Activación e integración (pendientes)

1. Confirmar quién tiene acceso al buzón `colab.marianosevilla@gmail.com` y quién puede abrir los adjuntos; revisar malware, riesgo de archivos maliciosos y control de acceso a soporte.
2. Política operativa **definida** (30 días como máximo en Gmail, eliminación anticipada): asignar responsable, comprobar acceso y ejecutar prueba de búsqueda/borrado definitivo en Gmail. La retención técnica de Resend es independiente y no puede purgarse mediante Gmail.
3. Aprobar la redacción del aviso y comprobarla contra la política de privacidad publicada. La opción es siempre separada de comunicaciones comerciales.
4. Verificar en pruebas sintéticas: sin consentimiento/no autenticado/origen ajeno/no habilitado/archivo inválido/error de proveedor, y una entrega simulada correcta.
5. Comprobar un envío sintético controlado antes de activarlo en producción. Autorizar por separado merge, despliegue y cambios de variables.
6. No modificar procesadores FIFO, archivos de clientes ni datos en producción.

La PR no demuestra eliminación física de backups, logs de proveedores ni copias de correo; tampoco debe usarse para afirmar cumplimiento RGPD integral.
