# About — publicación aprobada

Base: main b3342c3c8058417663decdef9efe248830ca5627. Tras revisar el preview, el titular autoriza su publicación el 18/10/2026: «ME gusta, pásalo a producción».

## Contenido confirmado por el titular

Mariano confirma la diplomatura en Informática de Gestión por la UPV y la experiencia descrita en ERP/CRM y dirección técnica de startups. Confirma que Rafael Ramos Martínez, colegiado 4.579 del Colegio de Economistas de Valencia, tiene más de 25 años de experiencia. Rafael define los criterios fiscales y funcionales que Mariano implementa, y además presta asesoramiento personalizado por separado. La generación automática de un informe no incluye una revisión profesional individual.

Se resumen las biografías para explicar la aportación de cada persona. La intermediación y la contratación y pago directos al profesional se describen de acuerdo con los términos y la política de privacidad publicados. No se promete revisión de cada informe, presentación ante Hacienda, unificación FIFO global, gratuidad del asesoramiento ni resultado fiscal garantizado.

## Diseño y fotografías

Se reutilizan header, footer, tipografía, hero verde, tokens de tarjetas y CTA aprobados del Home. Dos fichas estáticas de personas, sin hover que sugiera clic global; enlaces explícitos y accesibles. Las fotos y títulos se organizan con minmax(0,1fr), sin etiquetas nowrap. El contenido y los anchos se adaptan al texto ampliado.

Se reutilizan exclusivamente los seis WebP del Home ya presentes en el repositorio (88/176/264 px, ambos retratos). El par mayor suma 26.758 bytes frente a los 3.168.612 bytes de los dos PNG de About. No se regeneran ni se alteran rostros, no se incorporan binarios y no se instalan herramientas. Srcset, sizes, dimensiones explícitas y carga diferida permiten usar el tamaño adecuado.

## SEO y aislamiento

Título de marca y personas; AboutPage con dos Person y funciones visibles confirmadas. Los enlaces a UPV/COEV no se presentan como verificaciones públicas individualizadas del título o la colegiación. No se usa la página general del COEV como sameAs de Rafael. YouTube es un enlace, no un embed que cargue terceros.

La plantilla pública about.html reproduce el diseño aprobado con index,follow y canonical /about. La ruta Flask existente no cambia. Solo se actualiza la fecha de /about en el sitemap. La variante about_apple.html y el viewer permanecen noindex,nofollow. El viewer de Netlify sirve los WebP existentes desde el propio repositorio y utiliza session.json anónimo; la plantilla pública mantiene nav.js y la sesión real, sin simulaciones.

## Archivos y verificación

- static/about.html, static/about_apple.html, static/about_apple.css y scripts/build_about_preview.py: publicación, variante y reconstrucción.
- about-apple-preview/index.html y session.json: viewer aislado para revisión.
- tests/qa_about_apple.py, qa_responsive_nav.py y qa_responsive_layout.py: escenarios de navegador local, integración en el job existente.

La suite cubre 25 escenarios: producción en 13 anchuras, teclado, menú/Escape, ausencia de hueco superior, dos retratos decodificados, navegación sin JS, texto 200 %, movimiento reducido, sesiones sintéticas y paridad con el preview en móvil/escritorio. Las solicitudes externas o de escritura fallan el test. Los resultados ejecutados se documentan en la PR; esta declaración de cobertura no anticipa su éxito.

Sin cambios de lógica FIFO, Flask, datos, pagos, seguridad, variables, servicios, dependencias o workflows. Las comprobaciones no acceden a datos fiscales reales.
