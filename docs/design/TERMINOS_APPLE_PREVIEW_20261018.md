# Términos: preview visual y editorial — 18 de octubre de 2026

## Resultado y autorización

El usuario aprueba preparar una preview tras la auditoría de `/terminos`. La rama parte de main `25cbb944fed67984117d2225853dfb650a7fe37c`. No sustituye Términos de producción ni modifica contratos existentes, datos, archivos, cuentas, estadísticas, pagos, motores FIFO/721 o controles de seguridad. No fusionar esta rama como una entrega de producción: contiene visor y fixture locales.

## Diseño y alcance de archivos

Se reutiliza el HTML de header/footer de Privacidad publicada y los assets compartidos sin modificarlos: `nav.css`, `nav.js`, `landing_apple.css`, `landing_apple.js`, `legal_apple.css`. El footer marca Términos como página actual. Hero verde, tipografía del sistema, ausencia de CTA en el hero, índice lateral en escritorio e índice previo al contenido en móvil/tablet. Trece secciones permanecen visibles sin JavaScript; contacto final pertinente y estilos de impresión compartidos.

Archivos de esta entrega:

- `fiscal_app_export/static/terminos_apple.html`: variante aislada.
- `terminos-apple-preview/index.html`: visor autocontenido Netlify.
- `terminos-apple-preview/session.json`: exclusivamente `{"user":null}`.
- `fiscal_app_export/tests/qa_terminos_apple.py`: QA sintética específica.
- `fiscal_app_export/tests/qa_responsive_layout.py`: incorpora esa QA conservando las suites existentes, incluida Privacidad de producción.
- Este documento.

## Criterios de contenido

- Distinguir herramienta automática, solicitud de asesoramiento, intermediación de Mariano y prestación/contratación/pago directo a Rafa según el modelo comunicado. Mariano recibe una comisión, sin publicar importes personales.
- Describir el alcance real de archivos y resultados, incluyendo Excel admitido, flujos multifichero, PDF y preparación/XML del Modelo 721. No presentar una validación técnica como aceptación o presentación ante Hacienda.
- No atribuir de forma genérica el FIFO cripto al art. 37.2 LIRPF. Explicar monedas homogéneas y límites del historial aportado, sin afirmar consolidación automática entre exchanges.
- Sustituir la exoneración absoluta y la ausencia universal de garantías por límites específicos, preservando derechos y responsabilidades irrenunciables. No trasladar al usuario fallos de seguridad que no le sean imputables.
- No imponer fuero exclusivo en Valencia al consumidor. Remitir a la competencia legal aplicable.
- Distinguir baja de acceso, vaciado parcial del perfil y supresión de relacionados según Privacidad. No afirmar borrado total automático en 30 días. Aclarar que actualizar la explicación no extingue compromisos anteriores.
- Conservar los preavisos ofrecidos: quince días para cambios relevantes y treinta para cambios del acceso gratuito por introducción de planes de pago, sin limitar garantías adicionales. No usar el acceso continuado como aceptación universal ni modificar condiciones de cuentas existentes con esta preview.
- Diferenciar gratuidad actual de herramientas, recursos con precio y asesoramiento profesional. Los presupuestos/pagos integrados y nuevas cargas de documentos están suspendidos. No fijar precios, renovaciones, excepciones de desistimiento o reembolsos para productos futuros aún no definidos.
- Mantener el uso legítimo del informe para asesoría y obligaciones tributarias, separado de la propiedad intelectual del sitio.
- Orientación a adultos sin afirmar una comprobación automática de edad. Solo localidad autorizada Xirivella (Valencia); sin domicilio particular completo ni NIF privado.

## Límites y cuestiones de integración

Esta es una propuesta de redacción para revisión; su apariencia no constituye certificación legal. Identificación contractual completa, oferta profesional, aceptación/versionado, derechos adquiridos y condiciones de futuros cobros requieren revisión según su proceso real. Los enlaces del registro a `/legal/terminos` y `/legal/privacidad` no se reparan incidentalmente en una preview de presentación. No se ha implantado una prueba nueva de aceptación ni un control de edad.

La propuesta de suspensión proporcional y atención de incidencias incluye actuación humana por contacto; no anuncia una nueva función automática. La página no garantiza disponibilidad continua, pero tampoco usa «tal cual» para excluir obligaciones imperativas.

No se usa el enlace obsoleto de ODR/RLL ni se afirma adhesión a un arbitraje no verificado. Los mecanismos de reclamación quedan sujetos a los que correspondan legalmente.

## Aislamiento del visor

Se incorporan copias inline de los assets existentes. La copia del script de navegación consulta únicamente el fixture local del visor en lugar de `/api/me`; no se altera `window.fetch` ni el script compartido. Los enlaces externos al documento conducen a páginas públicas de producción. No hay formulario, tráfico a APIs productivas, credenciales ni información fiscal real. El visor tiene `noindex,nofollow` y canonical `/terminos`; no se añade fuente remota ni dependencia.

## Validación prevista

27 escenarios sintéticos en 13 anchos: variante estática y visor, ausencia de overflow, header sin hueco superior, un H1/main, índice y trece secciones visibles, salto al contenido, teclado, menú móvil, sesión demorada, roles ficticios, navegación sin JS, texto al 200 %, movimiento reducido e impresión. La prueba impide llamadas externas o mutaciones y mantiene las suites existentes de Home, Herramientas, Cómo funciona, Recursos, FAQ y Privacidad.

La ejecución asociada al commit de esta rama y la revisión del visor publicado aportarán el resultado final; no se presume un estado verde antes de observarlo. Los archivos de construcción locales no forman parte de la entrega.

## Producción posterior

Con el visto bueno específico, preparar una entrega limpia desde main vigente: sustituir únicamente el HTML final y añadir la QA de la ruta de producción, excluyendo visor/fixture/variante y recuperando la indexación adecuada. Evitar cambios en componentes compartidos que alteren Privacidad u otras páginas. Verificar CI y despliegue antes de comunicar la publicación.

## Fuentes de la auditoría

- https://www.boe.es/buscar/act.php?id=BOE-A-2007-20555 (TRLGDCU, actualización publicada 28/02/2026).
- https://www.boe.es/buscar/doc.php?id=DOUE-L-2019-80854 (Directiva 2019/770; consultar junto a su transposición).
- https://www.boe.es/buscar/act.php?id=BOE-A-2002-13758 (LSSI, contratación e información).
- https://www.boe.es/buscar/doc.php?id=DOUE-L-2016-80807 (RGPD, transparencia y derechos).
- https://sede.agenciatributaria.gob.es/Sede/ayuda/manuales-videos-folletos/manuales-practicos/irpf-2025/c11-ganancias-perdidas-patrimoniales/monedas-virtuales/compra-venta-monedas-virtuales-tributacion-inversor.html (criterio FIFO).
- Código de main auditado: `app.py`, `models.py`, `advisory_prefreeze.py`, `static/signup.html` y Privacidad publicada.
