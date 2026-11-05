# SEC5-PRIV — Protocolo propuesto de colaboración y reparto de datos con Rafael Ramos

**Corte:** 05/11/2026. **Estado:** BORRADOR INTERNO para contraste y acuerdo de las partes; **no está firmado ni aprobado como contrato, política pública, base legal o activación de cobros**.

**Alcance:** solo la relación de intermediación de asesoramiento fiscal a través de marianosevilla.com. No modifica el motor FIFO, el funcionamiento de cuentas, pagos Stripe, retenciones reales, derechos de descarga, analítica ni datos de producción. Este documento no contiene expedientes, identidades de clientes, correos privados, DNI, IBAN ni credenciales.

## 1. Hechos conocidos y límites de la evidencia

- **Manifestaciones del titular:** la colaboración con Rafael Ramos es actualmente verbal; Rafael es profesional autónomo/colegiado y cuenta con seguro de responsabilidad profesional. El flujo previsto es solicitud en la plataforma → valoración/presupuesto por Rafael → aceptación del interesado → futuro cobro → Rafael contacta al cliente y recibe **directamente en su correo profesional** la documentación fiscal; el trabajo y la custodia se realizan en su despacho.
- **Decisión de producto declarada:** la web no debe recibir ni guardar documentación profesional de asesoramiento. No confundir este flujo con las importaciones temporales CSV/Excel para cálculo FIFO, que sí procesa la herramienta.
- **Código y documentación del proyecto:** existen tablas `fiscal_advisory_requests`, `fiscal_advisory_files`, notas, auditorías y estados de asesoramiento en PostgreSQL, así como rutas heredadas. La ruta `POST /api/asesoramiento/solicitar` guarda datos y después invoca `_send_advisory_internal_notification`, que **puede remitir por Resend** a los destinatarios de `FISCAL_ADVISORY_NOTIFY_EMAILS` nombre, email, servicio, ejercicio fiscal, importe si existe y **hasta 500 caracteres de la descripción libre del caso**. Railway expone los nombres `FISCAL_ADVISORY_NOTIFY_EMAILS` y `RESEND_API_KEY`, pero no se han leído sus valores ni se ha acreditado un envío real, la identidad efectiva de destinatarios o sus garantías. La descripción puede contener información fiscal sensible y requiere revisión de minimización. `ENABLE_ADVISORY_UPLOADS` no figuraba entre nombres de variables Railway al 01/11 y el código usa `false` por defecto. **No se ha realizado una auditoría de datos reales** para certificar la ausencia histórica de archivos o PII.
- **Pagos:** reparto 70 % Rafael / 30 % Mariano y Stripe Connect son **intención de negocio**, no contratos ni operaciones activas demostradas. Según el titular no se han producido cobros reales del portal. Este borrador **no autoriza ni diseña** una pasarela, un reparto de fondos o facturación.
- **Infraestructura:** Railway ejecuta web y PostgreSQL; los proveedores de infraestructura y comunicaciones siguen un análisis contractual separado. La indisponibilidad del túnel SSH para crear un backup nuevo no autoriza cambios productivos ni la omisión de garantías.

**Consecuencia:** un acuerdo entre las partes puede definir obligaciones operativas, pero **no convierte automáticamente** a ninguno en responsable, corresponsable o encargado. La clasificación sigue los fines y medios de cada tratamiento realmente ejecutado.

## 2. Matriz propuesta por finalidad y sujeto responsable

| Actividad y datos mínimos | Propuesta de rol; pendiente de contraste | Custodia, acceso y límites |
| --- | --- | --- |
| Registro y autenticación web; importación FIFO; reportes y soporte de la plataforma | Mariano determina fines y medios de sus operaciones: **responsable** de estas finalidades | Plataforma y sus encargados que realmente correspondan; Rafael no necesita acceso al historial FIFO ni a cuentas |
| Formulario inicial de asesoramiento, estado de solicitud, contacto, propuesta y registro administrativo | Mariano, **responsable** de la captación/intermediación que gestione | Mantener solo campos necesarios; no replicar documentación fiscal extensa; los datos económicos y de atención se evalúan por finalidad |
| Avisos internos sobre la solicitud y comunicación a Rafael | **Comunicación entre posibles responsables independientes**, si el destinatario decide autónomamente fines y medios de su actuación; justificar el acceso y la información al interesado | El código ya tiene **envío condicional por Resend al crear la solicitud** a destinatarios configurados; puede incluir 500 caracteres de descripción y datos de contacto. **Revisar minimización, destinatarios reales, finalidad, seguridad y momento**, sin confundirlo con el envío posterior de documentos profesionales ni asumir que todo envío se realizó |
| Prestación profesional, llamadas, análisis fiscal, documentos que el cliente envía directamente a Rafael, dictamen y archivo profesional | Rafael, **probable responsable independiente** del expediente si actúa con criterio y medios propios, sujeto a sus obligaciones profesionales | Custodia en su despacho y correo profesional; Mariano no accederá al expediente salvo justificación específica y base válida |
| Presupuesto, cobro, comisión del 30 %, reembolso, disputa, factura | **Sin calificar todavía** el reparto de roles: depende del vendedor/prestador/cobrador y flujo Stripe efectivamente acordados | No activar ni informar como prestación implementada; requerirá acuerdo comercial y fiscal separado |
| Atención a derechos y reclamaciones sobre datos que custodia cada parte | Cada parte respecto de los tratamientos que controle; cooperación mínima en solicitudes cruzadas | No borrar por cuenta ajena; responder en plazo y comunicar el canal del responsable competente cuando proceda |

**Supuestos alternativos que exigen revisar la matriz:** si ambas partes deciden conjuntamente un mismo tratamiento, examinar **art. 26 RGPD** y formalizar corresponsabilidad; si Rafael tratase datos exclusivamente por cuenta e instrucciones de Mariano, aplicar **art. 28 RGPD** y su contrato de encargo. No imponer una etiqueta de «encargado» solo porque exista una comisión comercial.

## 3. Texto de trabajo para acuerdo con Rafael — cláusulas a validar

Los apartados siguientes se redactan como **propuesta contractual**, no como afirmación de acuerdos existentes.

### A. Objeto y autonomía profesional
Mariano gestiona una plataforma que canaliza solicitudes y comunicaciones comerciales de asesoramiento. Rafael decide autónomamente la aceptación profesional, el alcance técnico del servicio y la gestión de los documentos del expediente, en la medida efectiva en que tales decisiones le corresponden. Esta cláusula debe ajustarse al verdadero mecanismo de presupuesto, aceptación y pago.

### B. Transferencia mínima de información
Mariano y Rafael revisarán la comunicación **ya prevista en el código**: al registrar una solicitud la aplicación intenta enviar una notificación interna con datos personales mediante Resend, condicionada a la clave y destinatarios configurados. **No debe afirmarse que la aplicación carezca de envío automático**. Antes de declarar conforme el flujo, verificar el acceso efectivo, la necesidad y minimización de los campos —en particular, el extracto del relato libre—, el destinatario y la información ofrecida al interesado. Para valorar o prestar un servicio aceptado, solo se remitirán datos lícitamente obtenidos y necesarios por un medio seguro. No se presume que el consentimiento sea siempre la base adecuada. Rafael no reutilizará los contactos para campañas de la plataforma ni fines incompatibles. **Este borrador no cambia el envío existente.**

### C. Documentación profesional fuera de la web
Una vez establecido el vínculo profesional, el cliente remitirá su documentación fiscal **directamente a Rafael** mediante el canal indicado por este. Mariano no recibirá deliberadamente los adjuntos ni se constituirá en custodio del expediente. Si un cliente los enviase erróneamente a la plataforma o al soporte, se activará un procedimiento restringido de evaluación, respuesta y minimización, **sin reenviar silenciosamente información sensible**. Los posibles registros históricos `fiscal_advisory_files` requieren comprobación autorizada antes de prometer inexistencia o eliminación.

### D. Seguridad y confidencialidad
Cada parte protegerá los datos bajo su control mediante acceso mínimo, autenticación adecuada, custodia restringida, medidas contra divulgación accidental y gestión de incidentes conforme a su riesgo. La vía de comunicación de solicitudes entre partes deberá quedar identificada antes de uso; no incluir documentos fiscales en logs, repositorios, mensajes de CI o tickets. Los intercambios para soporte o derechos serán minimizados y trazables.

### E. Ejercicio de derechos y solicitudes
Cada parte facilitará un canal de ejercicio de derechos y responderá respecto de sus propios tratamientos. Si una solicitud recibida por Mariano se refiere a un expediente custodiado por Rafael, Mariano no borrará documentación ajena ni prometerá supresión integral; informará al interesado del canal aplicable y, cuando esté justificado, coordinará lo imprescindible con Rafael. La parte que reciba una comunicación dirigida a la otra procurará transmitir el aviso sin divulgar más datos de los necesarios. El plazo general del RGPD es **un mes**, con posibles prórrogas justificadas; esta coordinación no amplía automáticamente el plazo legal.

### F. Conservación y eliminación
Mariano aplicará **revisiones internas por finalidad** aprobadas el 02/11/2026; por ejemplo, evaluar solicitudes de asesoramiento **sin prestación ni pago a los 180 días desde su cierre real**, sin que sea una fecha de borrado automático. Rafael determinará los deberes de conservación y bloqueo que procedan sobre sus expedientes profesionales, sin exportarlos al portal por comodidad. Para pagos, reclamaciones y datos históricos sin titularidad clara, mantener `REVISION_ESPECIAL` hasta acreditar fundamento y custodia. Las copias antiguas requieren reconciliación antes de reabrir tráfico si se restaura una base.

### G. Incidentes, cambios y terminación
Ante un incidente que pueda afectar a datos compartidos, cada parte notificará **sin demora injustificada** a la otra la información mínima útil para contenerlo y determinar las obligaciones que correspondan a cada responsable. No prometer avisos legales automáticos sin valorar riesgo y rol. El fin de la colaboración no autoriza copiar el expediente profesional a la web, ni exige borrar justificantes sujetos a obligación legal.

### H. Pagos y facturación: cláusula separada, NO acordada
Antes de activar cobros deberán concretarse **por escrito** prestador contractual, vendedor/cobrador, factura al cliente, comisión de plataforma, costes Stripe, reembolsos, disputas, cuenta Connect y su reparto real. La intención **70/30** por sí sola no acredita quién es responsable de cada dato ni quién factura. Ninguna parte considera este borrador una autorización de pagos.

## 4. Comprobaciones que requieren decisión real de las partes

| Cuestión cerrable sin tocar producción | Estado |
| --- | --- |
| Rafael presta y custodia el servicio profesional fuera del portal, según el titular | **Declarado**, pendiente de aceptación expresa de Rafael |
| Mariano conserva datos de intermediación y registros técnicos en la plataforma | **Documentado**; no confundir baja de cuenta con supresión completa |
| ¿Quién comunica a Rafael los datos de la solicitud, en qué momento y por qué canal seguro? | **Código verificado:** notificación interna condicional por Resend al crear la solicitud; **pendiente:** destinatarios reales, legitimación y minimización del extracto libre, garantías, acuerdo efectivo entre las partes y si esa comunicación debe producirse antes de aceptar el presupuesto |
| ¿Rafael decide autónomamente el expediente, o hay fines/medios conjuntos en alguna fase? | **Por contrastar** antes de atribuir definitivamente roles |
| ¿Qué información entrega cada parte al cliente acerca de destinatarios y derechos? | **Por adaptar** a contrato y flujo real antes de publicación |
| ¿Qué servicios se cobran, quién emite factura y cómo se gestionan reembolsos? | **Pendiente de acuerdo comercial/fiscal**; no se resuelve mediante una cláusula RGPD |
| ¿Hay documentos profesionales heredados efectivamente almacenados en infraestructura? | **No comprobado**; no leer registros reales ni prometer ausencia sin revisión autorizada |
| ¿Se formaliza y archiva un acuerdo firmado por ambos? | **Pendiente**; este archivo no está firmado |

**Puerta de cierre de esta tarea documental:** las partes validan hechos y roles concretos, finalizan el acuerdo privado, asignan canales de atención y custodia, y posteriormente se revisa la transparencia pública. No publicar los datos identificativos, las firmas ni el contrato privado en GitHub.

## 5. Lo que esta PR no hace

No revisa cuentas ni expedientes reales; no lee Gmail de clientes; no modifica `/privacidad`, Flask, base de datos, `ENABLE_ADVISORY_UPLOADS`, Stripe, Railway, roles SQL, backups, automatizaciones, tarifas ni estadísticas; no genera documentos para firma con datos identificativos; no supone auditoría de cumplimiento ni cierra SEC5-PRIV global.

## 6. Referencias primarias y documentos relacionados

- [RGPD 2016/679, arts. 4(7-8), 5, 12, 13-14, 17, 26 y 28](https://eur-lex.europa.eu/legal-content/ES/TXT/?uri=CELEX%3A32016R0679).
- [AEPD — distinción responsable / encargado](https://www.aepd.es/preguntas-frecuentes/2-tus-obligaciones-como-responsable-del-tratamiento/8-responsable-y-encargado-del-tratamiento/FAQ-0251-como-se-si-soy-responsable-o-encargado).
- [AEPD — delimitación funcional en ecosistemas complejos (2026)](https://www.aepd.es/informes-y-resoluciones/criterios-juridicos-aepd/delimitacion-funcional-entre-responsable-y-encargado-tratamiento-ecosistemas-logisticos-y-tecnologicos): la denominación contractual por sí sola no determina el rol.
- [AEPD — deber de información claro](https://www.aepd.es/preguntas-frecuentes/2-tus-obligaciones-como-responsable-del-tratamiento/6-el-deber-de-informacion/FAQ-0247-como-debo-cumplir-con-el-deber-de-informar).
- Referencia del proyecto: `SEC5_PRIV_POLITICA_PARA_APROBACION_20261101.md`, `SEC5_PRIV_PROVEEDORES_BLOQUEO_EVIDENCIAS_20261101.md`, `SEC5_PRIV_DERECHOS_SUPRESION_PROCEDIMIENTO.md`, `SEC5_PRIV_CASE_REVIEW_20261102.md`.
