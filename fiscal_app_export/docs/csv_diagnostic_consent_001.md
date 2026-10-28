# 05-C3b · CSV-DIAG-CONSENT-001 — Envío voluntario de archivos fallidos

Estado: propuesta técnica en PR en borrador. No publicado ni habilitado.

## Objetivo

Permitir que una persona autenticada cuyo informe FIFO haya fallado comparta **voluntariamente un archivo concreto** para diagnóstico por soporte. El mero error de importación nunca dispara el envío. Se preservan los límites de privacidad de PR #154.

## Comportamiento propuesto

- Una opción adicional aparece después de ciertos errores de análisis solo si `CSV_DIAGNOSTIC_SUPPORT_ENABLED=true`.
- El usuario elige un fichero de su selección local y marca una casilla inicialmente vacía; un botón separado efectúa el envío.
- El servidor exige autenticación, origen permitido, un consentimiento explícito por petición, exchange válido, una sola extensión CSV/XLS/XLSX y tamaño de hasta 8 MiB. Hay un límite inicial de 2 intentos por día y cuenta.
- El servidor no copia deliberadamente el archivo a una tabla ni lo añade a la telemetría existente; lo transporta mediante la API de Resend a un destinatario fijo `CSV_DIAGNOSTIC_SUPPORT_EMAIL`. El nombre del adjunto es genérico.
- La respuesta no expone el archivo, claves, dirección de soporte ni detalles de terceros. No se reintenta automáticamente si se desconoce si Resend recibió la solicitud.
- En entornos sin configuración de correo o con el flag desactivado, el envío falla de forma cerrada.

## Riesgo de conservación — motivo para NO activar

**Este diseño no satisface todavía el requisito de borrado automático de copias:** Resend y el buzón receptor pueden conservar el adjunto y posibles copias. La aplicación no controla el ciclo de vida del buzón ni las copias del proveedor. Por ello no debe habilitarse el flag hasta acordar un plazo y un procedimiento verificable de eliminación y actualizar la información al usuario. Una alternativa más controlable sería un depósito privado temporal con caducidad y descarga administrativa, pero no existe bucket de archivos en Railway production; añadirlo exige decisión de infraestructura y coste.

La opción de correo presenta menos complejidad técnica y no exige almacenar temporalmente el archivo en PostgreSQL, pero amplía los receptores y deja persistencia fuera de la aplicación. No prometer borrado automático mientras no sea real y comprobable.

## Activación e integración (pendientes)

1. Confirmar el responsable del buzón y quién puede abrir los adjuntos; revisar malware, riesgo de archivos maliciosos y control de acceso a soporte.
2. Decidir el plazo de conservación, mecanismo de borrado del mensaje y adjuntos en mailbox/Resend y posibles copias, así como límites de lo que es posible eliminar.
3. Aprobar la redacción del aviso y comprobarla contra la política de privacidad publicada. La opción es siempre separada de comunicaciones comerciales.
4. Verificar en pruebas sintéticas: sin consentimiento/no autenticado/origen ajeno/no habilitado/archivo inválido/error de proveedor, y una entrega simulada correcta.
5. Comprobar un envío sintético controlado antes de activarlo en producción. Autorizar por separado merge, despliegue y cambios de variables.
6. No modificar procesadores FIFO, archivos de clientes ni datos en producción.

La PR no demuestra eliminación física de backups, logs de proveedores ni copias de correo; tampoco debe usarse para afirmar cumplimiento RGPD integral.
