# SEC5-PRIV-011/012/013 — Procedimiento mínimo para solicitudes de supresión

**Estado:** procedimiento de gestión propuesto; no es política de retención aprobada ni orden de purga.  
**Fecha:** 01/11/2026 · **Base:** `main@0307dfdf382e2d6d024201a99a2fd2b100415f87`.  
**Finalidad:** facilitar el ejercicio de derechos sin destruir registros necesarios ni prometer borrados inexistentes. No es un mecanismo técnico completo de bloqueo.

## Alcance real y responsabilidades

- **Mariano Sevilla:** responsable, en principio, de las finalidades y medios que decide para cuentas, cálculo FIFO, gestión de solicitudes, soporte y comunicaciones de la plataforma. No convertir la web en un archivo documental fiscal. La atribución exacta de responsabilidades debe coincidir con el acuerdo de intermediación efectivo.
- **Rafael Ramos:** según el titular, **custodia la documentación fiscal de los clientes** para el asesoramiento que presta. Revisar su condición de responsable respecto de los expedientes y qué datos de solicitud, notas o documentos siguen bajo control de la plataforma. No asumir que una petición a Mariano autoriza a borrar expedientes profesionales custodiados por Rafael.
- **Plataforma:** conserva también registros personales operativos, algunos con referencias a cuenta o correos duplicados, según inventario de 17 tablas ORM en `SEC5_PRIV_011_013_RETENTION_MATRIX.md`. Un CSV/PDF temporal y un registro persistente son categorías diferentes.
- **Otros sistemas:** Gmail, Resend, Stripe, Railway, logs, backups, restos de adjuntos históricos. No afirmar que desaparecen por una baja de cuenta o por un borrado en PostgreSQL.

**Distinción imprescindible:** `POST /api/delete-account` verifica identidad y desactiva el acceso; elimina identificadores principales y credenciales en `users`; **no suprime ni bloquea integralmente** las tablas relacionadas. El resultado de esa API debe decirlo sin ambigüedad.

## Flujo operativo de atención a derechos, sin automatizar borrados

1. **Recepción:** aceptar solicitudes por `colab.marianosevilla@gmail.com` y por cualquier canal válido empleado por el interesado. Registrar de forma restringida **fecha de recepción**, tipo de derecho y plazo de respuesta. No exigir que la persona conserve una cuenta activa para solicitar supresión.
2. **Verificación proporcional:** comprobar identidad únicamente cuando sea necesario para evitar actuar sobre datos de un tercero. Si la cuenta sigue activa, localizar primero el vínculo técnico y las referencias relacionadas **antes** de reemplazar el email por `deleted_<id>@deleted`. Si ya se desactivó, utilizar evidencia proporcionada voluntariamente y criterios seguros; **no ejecutar eliminaciones por simple coincidencia de nombre o email ambiguo**.
3. **Inventario por finalidad:** revisar cuentas y dependencias por `user_id`, correos copiados en `processing_errors`, `contactos`, `resource_requests`, `communication_deliveries`, solicitudes de asesoramiento y las tablas S01. Verificar también externos y archivos temporales/históricos si corresponde. Clasificar cada dato como necesario para servicio activo, conservación justificada, bloqueo legal o supresión; no confundir datos de terceros con los del solicitante.
4. **Decisión motivada:** separar **baja técnica**, **supresión legal**, **bloqueo** y **excepción**. No ejecutar borrado en cascada sobre pagos, reembolsos, derechos de descarga, incidencias abiertas o expedientes. Para bloqueo del art. 32 LOPDGDD se exige impedir consulta y tratamiento ordinario con acceso excepcional restringido y demostrable; `archived`, `resolved` o `is_active=False` por sí solos no bastan.
5. **Respuesta:** comunicar sin dilación indebida, normalmente dentro de **un mes** desde la recepción; si procede prórroga de hasta dos meses adicionales, informar motivadamente dentro del primer mes. Explicar qué se suprimió, qué se retuvo o bloqueó, por qué y qué terceros custodios deben atender la solicitud por su cuenta, sin revelar datos de terceros.
6. **Prueba y trazabilidad mínima:** conservar evidencia restringida de recepción, análisis, decisión, actuación y respuesta según necesidad y plazo justificables. Nunca guardar una copia completa del CSV o la documentación profesional solo para demostrar que se atendió la solicitud. Si hay copias de seguridad o correos, registrar el tratamiento o excepción verificable, no afirmar borrado universal.
7. **Cierre:** confirmar el resultado real de cada sistema y actualizar la información pública solo después de comprobarlo. Un correo contestado no demuestra borrado en todos los proveedores.

## Criterios legales comprobados (fuentes primarias)

- RGPD, arts. 5.1(c/e), 12.3, 17 y 28: minimización, limitación temporal, atención de derechos, excepciones a supresión y contratos con encargados: https://eur-lex.europa.eu/eli/reg/2016/679/oj
- LOPDGDD, art. 32 (bloqueo y destrucción tras prescripción aplicable): https://www.boe.es/eli/es/lo/2018/12/05/3/con
- AEPD, derecho de supresión y sus excepciones: https://www.aepd.es/preguntas-frecuentes/1-tus-derechos/2-tus-derechos-de-proteccion-de-datos/FAQ-0111-que-es-el-derecho-de-supresion-derecho-al-olvido
- AEPD, plazo de respuesta: https://www.aepd.es/preguntas-frecuentes/1-tus-derechos/2-tus-derechos-de-proteccion-de-datos/FAQ-0106-cual-es-el-plazo-para-responder-cuando-se-ejercitan-estos-derechos
- AEPD, distinción responsable/encargado: https://www.aepd.es/preguntas-frecuentes/2-tus-obligaciones-como-responsable-del-tratamiento/8-responsable-y-encargado-del-tratamiento/FAQ-0251-como-se-si-soy-responsable-o-encargado

## Pendiente para cerrar la fase SEC5-PRIV-011/012/013

- Aprobar por finalidad la **base jurídica, desencadenante, plazo de conservación, excepción y destino** de las categorías de datos. Los 30/90/180 días documentados previamente son hitos de revisión propuestos, no períodos impuestos por ley.
- Precisar contractualmente el circuito con Rafael y el custodio de los documentos; no atribuir automáticamente a Mariano la conservación documental profesional.
- Verificar condiciones aplicables de proveedores, transferencias internacionales y conservación/restauración de backups.
- Diseñar y ensayar bloqueo/supresión con pruebas sintéticas, integridad financiera y aislamiento entre usuarios, antes de solicitar aprobación para migraciones o actuaciones sobre datos reales.
- Alinear la política pública con capacidades probadas y corregir la discrepancia de sesiones documentada aparte en [PR #169](https://github.com/MarianoSevilla/fiscal-cripto-/pull/169).

**No ejecutado:** supresión, bloqueo, traslado de datos, acceso a producción, cambios de permisos, consultas a expedientes, envíos de correo o cambios en Stripe. El único ajuste de runtime de esta intervención es el mensaje de respuesta de desactivación de cuenta; la lógica existente de confirmación de identidad y desidentificación permanece intacta.
