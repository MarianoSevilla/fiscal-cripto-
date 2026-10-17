# FAQ · variante para revisión

Base: main acd3c08bfb605582813e78f683b58d6ae721053b. Autorización del propietario: preparar la versión de prueba tras auditoría y datos Search Console, 17/10/2026. No autoriza publicación de /faq.

Alcance: nuevo static/faq_apple.html, faq_apple.css y faq_apple.js; raíz estática faq-apple-preview/index.html para Netlify; qa_faq_apple.py e incorporación al runner responsive ya existente. Se reutilizan header/footer y activos Home sin modificarlos. No se cambian FAQ original, rutas, motores FIFO, app.py, políticas, pagos, servicios, configuraciones ni dependencias.

20 preguntas en cuatro grupos; orden inicial historial/FIFO por consultas reales de Search Console (España, web, 17/07–14/10/2026). Las impresiones no equivalen a volumen de mercado. Preguntas nativas details/summary, varias abiertas, soporte sin JS, enlaces de categorías y apertura por ancla con mejora JS. Hero de ancho completo y CTA con clases Home aprobadas. Sin buscador ni terceros de analítica. Noindex/nofollow en variante y preview; canonical /faq. WebPage existente de producción no se modifica. No se añade marcado FAQ para prometer resultados enriquecidos.

## Revisión editorial antes de cualquier integración

- Rafa debe revisar las nueve respuestas de Declaración e impuestos y el criterio FIFO entre plataformas. Se distingue generar renta de estar obligado a presentar; no se publican casillas universales ni mínimos exentos de cripto. En staking/airdrops se conserva deliberadamente una redacción de alcance y casuística, sin atribuir revisión profesional ya hecha.
- Referencias oficiales consultadas: manual AEAT IRPF 2025, compra/venta/permuta de monedas virtuales; FAQ AEAT Modelo 721; fuentes detalladas en Auditoria_FAQ_marianosevilla_2026-10-17.md. No se afirma que una plataforma concreta comunica determinados datos a Hacienda en un ejercicio específico.
- Tratamiento de datos: la nueva respuesta reconoce temporales y registro de datos de informes que existen en app.py. Falta confirmar plazos, finalidad detallada y limpieza de todos los casos; no se inventan garantías. La política actual conserva contradicciones identificadas en auditoría: su corrección necesita alcance y validación propios antes de publicar esta variante.
- Cuenta/precio: crear cuenta gratis no equivale a informe completo gratuito. Completar condiciones comerciales cuando estén definidas; no se inventa un producto descargable gratis ni se promete asesoramiento activo.
- Compatibilidad: catálogo mantenido por exchange; no se promete consolidación global automática ni cobertura de todos los tipos de operación.

Estas observaciones son para revisión interna y no aparecen como mensajes provisionales en el contenido de la página. La variante no se debe fusionar hasta cerrar revisión fiscal, privacidad y condiciones comerciales.

## Verificación

Suite responsive añadida: 13 anchos, geometría del header sin espacio inicial, menú, 20 preguntas, teclado, varias abiertas, cuatro anchos sin JS, zoom de texto 200%, anclas, movimiento reducido y roles sintéticos. Intercepta API de sesión y prohíbe solicitudes externas/escrituras. Capturas en artefactos CI. La preview autónoma simula visitante y bloquea llamadas de backend; enlaces ordinarios llevan a las páginas reales. El mock no debe integrarse en producción.

Entorno local: Playwright de Node preinstalado, pero no hay ejecutable Chromium disponible. No se descarga ni instala. Se usa el navegador disponible para revisión visual y la dependencia de navegador del flujo CI ya existente para la matriz. No dar la matriz por superada antes de comprobar CI.

## V2 · revisión editorial tras investigación externa

Autorización: «procede con la actualización del preview», 17/10/2026, 21:00 Europe/Madrid. Base del prototipo: 77436013362edc9d8a511e8ff2b27d6ab660e27d. Solo se modifican static/faq_apple.html, faq-apple-preview/index.html y este documento. Las veinte preguntas, grupos, IDs, header/footer, CSS y JS se conservan; no se integra en main ni en /faq.

Se incorporan quince respuestas más precisas y enlaces directos a fuentes. Se distingue obligación de presentar de obtención de renta; permuta con el mayor valor de mercado; pérdidas por transmisiones frente a estafas y créditos no cobrados; staking de inversor sin generalizar a toda validación; airdrops con sus condiciones; titularidad/poder de disposición del 721 sin llamar custodio al usuario. No se introduce un plazo automático de recompra, una casilla fiscal universal o un coste de adquisición cero por defecto.

Fuentes contrastadas el 17/10/2026:
- AEAT IRPF 2025, compra/venta/permuta y créditos no cobrados: https://sede.agenciatributaria.gob.es/Sede/ayuda/manuales-videos-folletos/manuales-practicos/irpf-2025/c11-ganancias-perdidas-patrimoniales/monedas-virtuales/compra-venta-monedas-virtuales-tributacion-inversor.html
- AEAT IRPF 2025, obligación de declarar: https://sede.agenciatributaria.gob.es/Sede/ayuda/manuales-videos-folletos/manuales-practicos/irpf-2025/c01-campana-declaracion-renta/quienes-estan-obligados-presentar-declaracion-irpf/delimitacion-obligacion-declarar-irpf.html
- AEAT Modelo 721, condiciones y pérdida de condición: https://sede.agenciatributaria.gob.es/Sede/todas-gestiones/impuestos-tasas/declaraciones-informativas/modelo-721-decla-sobre-monedas-extranjero/preguntas-frecuentes-sobre-modelo-721.html
- DGT, Memoria 2024, páginas impresas 70–71 (PDF 86–87), resumen oficial de V0648-24: https://www.hacienda.gob.es/sgt/tributos/memorias/memoria-2024.pdf#page=87
- DGT V1828-24: https://petete.tributos.hacienda.gob.es/consultas/?num_consulta=V1828-24 . Su texto completo se obtuvo en el resultado indexado oficial: estafa con autor desconocido, sin crédito identificable, pérdida que debe justificarse. No imponer siempre artículo 14.2.k. La apertura simple puede mostrar solo la interfaz del buscador.

Los informes externos aportados se trataron como material para contrastar: no se adoptaron todas sus conclusiones ni las etiquetas «Verificado». Las respuestas siguen pendientes de revisión fiscal por Rafa; no se le atribuye visto bueno. Recompra, comisiones abonadas con otro activo, cashback y modalidades de staking requieren valoración específica si se pretende ampliar su tratamiento.

Comprobación técnica de solo lectura: app.py conserva blob e386f57b8ca066bfde262656ba41ed2d7a987559 en main acd3c08bfb605582813e78f683b58d6ae721053b. No se importa ni ejecuta la aplicación ni se consultan datos de usuarios. Líneas 2169–2195: validación de diez exchanges en el recorrido principal; MEXC XLS/XLSX, Bit2Me Excel condicionado por flag no inspeccionado, resto CSV. Existen recorridos específicos de KuCoin y Bitget. Por ello no se promete Excel general ni una lista exhaustiva de cobertura completa. Líneas 2444–2478: generación y respuesta con PDF/resumen/advertencias. Líneas 485–508: registro de usuario, exchange, ejercicio, métricas y resultados. Líneas 2536–2546: intento de limpieza de temporal en finally; líneas 3398–3409: intento de borrado de PDF tras margen de dos segundos. No garantizan borrado efectivo en cualquier situación, ni cierre de retención de registros, backups o PDFs no descargados.

La FAQ informa de procesamiento temporal, PDF y datos de informes, sin prometer cifrado no auditado, ausencia de datos guardados o cumplimiento total. Retención y coherencia de la política de privacidad continúan pendientes de su revisión propia. Crear cuenta gratis se mantiene separado de prestaciones e informes; no se inventan tarifas o descargas gratuitas. No cambia la seguridad ni el procesamiento.

Validación V2: comparación estructural de los veinte títulos/IDs y header/footer/CSS/JS; sintaxis y enlaces; la matriz responsive existente se ejecuta de nuevo porque cambian longitudes y enlaces de las respuestas. Resultados finales en la PR102, antes de entregar la preview.
