# Publicación Home/Herramientas V8 · 17/10/2026

Autorización del propietario: «visto bueno, te autorizo a actualizar la web», 13:22 Europe/Madrid. Fuente aprobada PR #96 @7164ab07dd97973d680e77ec288b10b8f698f7c7; Required CI 39028085027 SUCCESS.

Integra seis archivos de producto/QA idénticos por blob a la fuente aprobada. Excluye vistas raíz Netlify, simuladores y documentación de iteraciones. Base main@789c559a0897c9185e39701debfd57e8b61785b2.

Home conserva HTML, navegación y contenido; el CSS compartido unifica sus tarjetas con Herramientas. Esta última usa cabecera verde coherente con Home y tarjetas compactas de título, descripción y enlace. Aviso de presupuestos/pagos de asesoramiento suspendidos visible, destinos originales y FAQs intactos. Sin alturas fijas ni recortes. Hover 150 ms, foco visible, movimiento reducido y enlace extendido a toda la tarjeta por CSS.

Archivos de producto: static/landing_apple.css, static/herramientas_apple.css, static/herramientas.html. QA: tests/qa_home_redesign.py, qa_herramientas_redesign.py y test_herramientas_redesign.py. El fixture V5 se conserva y el contrato protege todo el HTML fuera del catálogo. QA compara estilo y ancho de las dos páginas en 13 anchos; Home 26 y Herramientas 24 escenarios sintéticos.

Sin cambios de Flask, sesiones, FIFO, controles de seguridad, pagos, DB, variables, workflows ni dependencias. Publicar solo tras CI de integración correcto, verificar commit nuevo en Railway SUCCESS y contenido público coincidente. Baseline para rollback: deployment 4caedfd8-da1f-448f-b4f3-e4296ddffba9 / main@789c559a0897c9185e39701debfd57e8b61785b2.
