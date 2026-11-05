# SEC5-PRIV — Contraste documental de proveedores y transferencias

**Corte de comprobación:** 05/11/2026. **Estado:** investigación documental cerrada a este corte; **evidencia contractual de cuenta parcialmente pendiente**. Documento **interno**, sin datos de clientes ni certificados privados; no constituye un dictamen de conformidad RGPD, una orden de cambios, firma contractual ni un permiso de purga.

**Objeto:** Railway (web y PostgreSQL), Resend (correo), Google/Gmail (buzón de soporte) y Stripe (integración/pagos). Complementa —no sustituye retrospectivamente— las observaciones del 01/11/2026 en `SEC5_PRIV_PROVEEDORES_BLOQUEO_EVIDENCIAS_20261101.md`. No reabre diseño de retenciones, estadísticas ni Stripe Connect.

## 1. Método y evidencia efectivamente comprobada

- **Fuente pública:** documentos oficiales enlazados en §8, leídos el 05/11/2026. Sus condiciones genéricas **no prueban** la modalidad, aceptación, suscripción, configuración, firma efectiva, certificación de transferencia de la entidad concreta o comportamiento real de una cuenta.
- **Railway de este proyecto (lectura, 05/11):** producción `fiscal-cripto-` y `Postgres` en `SUCCESS`, último web commit `3362f051acd652bf207c2000279003fe3bbd9652`, sin cambios staged ni despliegues pendientes. El último despliegue web indica región `us-east4-eqdc4a`; el volumen `postgres-volume` de 5.000 MB aparece en esa región. No hay volumen persistente asociado al servicio web ni buckets listados. La documentación previa identifica esa región como Virginia, EE. UU. Esta comprobación **no es prueba** de inventario completo de subencargados, transferencias auxiliares, backups habilitados o cumplimiento de cláusulas.
- **Código/entorno descritos previamente:** Resend se emplea para comunicaciones condicionales y el buzón operativo conocido es una dirección `@gmail.com`; Stripe está integrado técnicamente, pero el modelo 70/30 de asesoramiento y los informes FIFO de pago futuros no se consideran operativos por ese solo hecho. No se han leído valores de claves, contratos privados, mensajes, documentos profesionales, cobros ni filas de la base de datos.
- **Prohibiciones de alcance:** no se utiliza SSH/SQL sobre producción, no se crea/restaura ninguna copia, no se envía correo, no se acepta un DPA, no se modifica un contrato, proveedor, acceso, configuración o política web. Este archivo no contiene identidades fiscales, firmas ni tokens.

## 2. Matriz de evidencias por proveedor

| Proveedor y función | Condiciones públicas confirmadas a este corte | Estado específico de la cuenta y límite | Prioridad y acción mínima |
| --- | --- | --- | --- |
| **Railway — web, PostgreSQL y logs** | [DPA Railway](https://railway.com/legal/dpa): Railway actúa en general como **encargado** para contenido del cliente y como **responsable independiente** de ciertos datos propios de cuenta/uso. Prevé transferencia internacional mediante SCC y/o DPF cuando proceda, además de subencargados. **La sección “Execution of this DPA” exige remitir un formulario DocuSign y que Railway lo ejecute** para perfeccionar ese DPA. Se contemplan obligaciones y medidas técnicas, pero no constituyen evidencia directa de su ejecución contractual para esta cuenta. | **Región de servicios y volumen verificada en EE. UU.** No se dispone de copia del DPA cumplimentada y ejecutada, ni confirmación de su firma efectiva. No asumir que visualizar el texto público acredita el contrato. No existe verificación nueva de backups Railway; el volumen no es un backup. | **P1:** comprobar de forma privada si existe el DPA ejecutado para la parte contractual correcta. Si no, tramitarlo mediante el flujo oficial **con aprobación expresa del titular para la firma**. Guardar copia fuera del repositorio. Revisar lista de subencargados y transferencias al archivo de cumplimiento, no como dato público. |
| **Resend — envíos transaccionales y soporte** | [GDPR Resend](https://resend.com/security/gdpr) y [DPA](https://resend.com/legal/dpa): **el DPA art. 28 se considera prefirmado y vinculante al alta de la cuenta**, sin contrafirma adicional. Copia propia descargable en **Settings → Documents**. Almacenamiento de mensajes y logs en **EE. UU.**, aunque se seleccione región de salida UE. SCC incorporadas; Resend comunica participación en DPF. En **Free/Pro/Scale**, correos/logs 30 días y backups 7 días; Enterprise permite ajustes. No ofrece API para borrar un correo individual; solicitud anticipada por soporte indicando IDs de mensajes. | **No hay copia extraída del DPA de la cuenta ni modalidad comercial verificada**. La fuente pública sí aclara el régimen contractual por defecto, por lo que **no es correcto exigir una firma adicional de Resend** como paso general. Tampoco se han comprobado certificados, envíos ni borrados reales en esta auditoría. | **P1, bajo coste:** descargar y archivar privadamente DPA desde el panel, confirmar plan/retención aplicables y documentar la vía de borrado puntual. No modificar correos, activar diagnósticos ni crear nuevas copias de mensajes. |
| **Google — Gmail de soporte** | [Ayuda oficial Gmail](https://support.google.com/mail/answer/7401?hl=es): un correo enviado a Papelera es recuperable hasta 30 días, con opción de borrado permanente anterior. La [política general de retención de Google](https://policies.google.com/technologies/retention) contempla procesos prolongados y copias cifradas hasta 6 meses; **no es un SLA particular de borrado de un mensaje**. El [Cloud DPA de Google Workspace/Cloud Identity](https://knowledge.workspace.google.com/admin/compliance/privacy-compliance-and-records-for-google-workspace-and-cloud-identity) se refiere a **productos/contratos Workspace**, no se incorpora automáticamente a una cuenta Gmail estándar. **Matiz:** también existe una [modalidad Google Workspace Personal](https://workspace.google.com/terms/workspace-personal-terms/) para cuentas `@gmail.com` con términos adicionales y DPA para los productos cubiertos, cuando se contrata; no inferir modalidad por el dominio. | Buzón operativo `@gmail.com` conocido; **tipo exacto de suscripción y cobertura contractual sin acreditar**. No es correcto afirmar ni que toda cuenta `@gmail.com` sea Workspace ni que Google Workspace nunca pueda cubrir una dirección `@gmail.com`. La compra de Workspace no se presupone necesaria sin evaluar tratamientos y contrato. | **P1:** identificar el producto/plan realmente contratado y términos aplicables. Mantener los CSV de diagnóstico voluntario sujetos a revisión de soporte según política, pero no equiparar “Papelera” con borrado de todas las copias. No abrir el buzón ni revisar expedientes personales en esta intervención. |
| **Stripe — pagos y cuenta comercial** | [DPA Stripe, 28/09/2026](https://stripe.com/legal/dpa): **incorporado por referencia al acuerdo de servicios**, con doble régimen según finalidad: encargado del usuario en determinadas operaciones y responsable independiente en fraude, AML/KYC, relaciones operativas y obligaciones legales. Incluye [adenda de transferencias](https://stripe.com/legal/dta) y relaciones con subencargados. [Centro de privacidad](https://stripe.com/legal/privacy-center): conservación variable, con necesidades de defensa, pagos y cumplimiento; describe **en general cinco años o más** para ciertos datos de usuarios empresariales en muchas jurisdicciones, **no** un plazo universal para toda fila local del portal ni toda categoría de dato. | No se han contrastado desde la cuenta los productos activos, la parte contractual concreta, los saldos/cobros, la modalidad Connect ni los datos realmente enviados. Las hipótesis del 70/30, del vendedor/prestador y de facturación siguen abiertas para antes de activar cobros. | **P2, ligada a monetización:** identificar acuerdo y productos efectivos al diseñar cobros FIFO 2027 y asesoramiento, documentar papeles y flujos, y conservar el DPA correspondiente. **No** inferir conservación obligatoria local de cinco años por la frase genérica de Stripe. No cambiar configuración de pagos en SEC5-PRIV. |

## 3. Transferencias internacionales: decisión proporcionada

1. La **ubicación verificada** de Railway en Virginia y la **declaración oficial** de almacenamiento de Resend en EE. UU. son hechos diferentes de la **validez jurídica** del mecanismo de transferencia. La residencia estadounidense por sí sola **no demuestra una infracción** ni obliga a migrar en este momento.
2. Los contratos públicos prevén **cláusulas contractuales tipo (SCC)** y, en determinados supuestos, **Data Privacy Framework (DPF)**. La [Comisión Europea](https://commission.europa.eu/law/law-topic/data-protection/international-dimension-data-protection/adequacy-decisions_en) reconoce adecuación solo para entidades de EE. UU. participantes en el marco, no para todas las empresas estadounidenses. **No se verificó en esta revisión el estado registral actualizado de certificación DPF de cada entidad legal receptora**. No presumirlo.
3. La evaluación concreta debe identificar entidad contractual, datos y finalidad, subencargados/países y mecanismo efectivo, y valorar medidas técnicas y organizativas proporcionales. **No confundir** medidas declaradas públicamente con auditoría de su funcionamiento real. Tampoco declarar “cumplimiento RGPD garantizado” en la web.
4. No se propone por defecto migrar PostgreSQL a la UE, contratar Enterprise o reemplazar Gmail/Resend; antes se requieren evidencia, coste, impacto operativo y riesgo material. Si el DPA de Railway no se hubiera ejecutado, corregir la base documental sería más eficiente y menos arriesgado que rediseñar el hosting.

## 4. Ciclo de conservación y ejercicio de derechos: límites concretos

- **Railway:** el DPA no acredita un plazo único de supresión por expediente ni existencia de backup del proyecto. La conservación de cuentas/uso de Railway es una finalidad propia distinta de los registros de usuarios de `marianosevilla.com`.
- **Resend:** 30 días de mensajes/logs en planes declarados y 7 días de backups no son plazos de borrado de Gmail ni prueba de que un correo concreto se haya suprimido. Un correo individual necesita trámite con soporte para anticipar su retirada; no existe endpoint de borrado individual según la documentación del 05/11.
- **Gmail:** el borrado permanente desde Papelera elimina acceso normal al mensaje, pero no permite afirmar eliminación inmediata de todos los sistemas técnicos de Google. Separar la política interna de diagnóstico (máximo operativo previsto de 30 días) del ciclo del proveedor y de cualquier obligación particular.
- **Stripe:** no prometer purga universal al cerrar la cuenta local; algunas categorías tienen fines de fraude, obligaciones y reclamaciones. Cualquier petición real exige individualización y comunicación al responsable que corresponda.
- **Todos:** el bloqueo/supresión art. 32 LOPDGDD sigue **sin implantarse como sistema legal real en producción**. Las pruebas sintéticas PostgreSQL 18 ya incorporadas no autorizan borrar datos ni demuestran ejecución contractual del proveedor. La reconstrucción tras restaurar una copia antigua continúa condicionada a reconciliar actuaciones posteriores.

## 5. Evidencias privadas mínimas pendientes — sin nuevos proyectos

1. **Railway (prioridad alta):** localizar constancia y copia ejecutada del DPA DocuSign, confirmar la **parte contratante exacta** y la fecha. Si está ausente, requerirá la **decisión/firma explícita** del titular; no registrar “firmado” sin prueba.
2. **Resend (prioridad alta):** copia del DPA desde Settings → Documents y confirmación del plan. **No pedir que el titular comparta en GitHub contratos firmados o documentos con datos identificativos**; conservarlos en custodia privada y registrar solo que la evidencia existe y cuándo se verificó.
3. **Gmail (prioridad alta):** indicar si el buzón es una cuenta estándar o tiene modalidad Workspace Personal/otra. En el caso de Workspace, comprobar el contrato y DPA concreto; no adquirir un producto como solución automática.
4. **Stripe (diferido hasta el diseño de cobro):** precisar las funcionalidades contratadas y roles al fijar vendedor, factura y modalidad de pago; no usar el DPA genérico como prueba de conciliación financiera.

El usuario **no tiene que compartir documentos de terceros con datos personales** para esta fase. Si hubiera que comprobar un DPA firmado, bastaría una verificación privada de existencia/fecha/entidad, y una revisión del documento con acceso restringido si fuera imprescindible.

## 6. Puerta de aceptación y cierre de este subtrabajo

**Confirmado a 05/11/2026:**
- Se han contrastado las **cuatro fuentes oficiales**; corregida la hipótesis previa de firma adicional para Resend y el simplismo `@gmail.com = sin DPA` en cualquier modalidad.
- Railway production permanece estable en el commit observado; no se ha accedido a datos reales.
- Identificados **tres controles de cuenta** de bajo coste y el control Stripe condicionado al futuro producto.

**No confirmado:** DPA ferroviario (Railway) efectivamente firmado, copia privada Resend, plan Gmail/Resend, entidad receptora DPF por certificación, Stripe Connect, acceso específico a expedientes, borrados y retención real de cada proveedor.

**Resultado:** `INVESTIGACION_PUBLICA_PASS / CONTRATO_CUENTA_NO_VERIFICADO`. Este subtrabajo documental puede archivarse tras revisión de la PR; **SEC5-PRIV global permanece ABIERTA**. No autoriza cambios de producción, compra de servicios, firma de DPA, difusión pública de contratos, migración, supresión ni despliegue.

## 7. Proporcionalidad de los próximos pasos

No abrir una reforma general de infraestructura. Bastan los controles privados del §5 para aclarar el principal riesgo contractual; las decisiones de bloqueo legal, conservación por categoría y restauración de backups deben continuar separadas y con su aprobación. El acuerdo con Rafael preparado en la PR #185 no constituye contrato firmado y necesita contraste por ambas partes. Evitar vincular la monetización FIFO a cambios innecesarios de hosting.

## 8. Fuentes primarias consultadas

- [Railway — DPA y proceso DocuSign](https://railway.com/legal/dpa)
- [Railway — política de privacidad](https://railway.com/legal/privacy)
- [Railway — subencargados](https://trust.railway.com/item/subprocessors)
- [Resend — DPA, 31/12/2025](https://resend.com/legal/dpa)
- [Resend — GDPR, contrato por alta, residencia, SCC/DPF, plazos, supresión individual](https://resend.com/security/gdpr)
- [Resend — seguridad](https://resend.com/security)
- [Google — supresión Gmail y Papelera](https://support.google.com/mail/answer/7401?hl=es)
- [Google — ciclo de retención general](https://policies.google.com/technologies/retention)
- [Google Workspace/Cloud Identity — CDPA y aceptación](https://knowledge.workspace.google.com/admin/compliance/privacy-compliance-and-records-for-google-workspace-and-cloud-identity)
- [Google Workspace Personal — términos adicionales](https://workspace.google.com/terms/workspace-personal-terms/)
- [Stripe — DPA, 28/09/2026](https://stripe.com/legal/dpa)
- [Stripe — centro de privacidad y retención](https://stripe.com/legal/privacy-center)
- [Comisión Europea — países y organizaciones con adecuación](https://commission.europa.eu/law/law-topic/data-protection/international-dimension-data-protection/adequacy-decisions_en)
- [RGPD, arts. 5, 13, 28 y 44-46](https://eur-lex.europa.eu/eli/reg/2016/679/oj?locale=es)

**Relación con documentos del proyecto:** `SEC5_PRIV_PROVEEDORES_BLOQUEO_EVIDENCIAS_20261101.md`, `SEC5_PRIV_POLITICA_PARA_APROBACION_20261101.md`, `SEC5_PRIV_RAFA_ACUERDO_COLABORACION_BORRADOR_20261105.md` y `SEC5_PRIV_BACKUP_RECOVERY_RUNBOOK_20261103.md`.
