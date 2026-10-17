# V7 · Tarjetas de catálogo compartidas

Solicitud del propietario: unificar los catálogos de exchanges y herramientas y añadir el feedback de Home. Se conserva la cabecera V6 aprobada visualmente. Solo vista previa, sin producción.

Se añade un componente al final de landing_apple.css, sin cambiar su prefijo previo: mismos tokens, fondo verde #edf5f0, borde #b9d8cb, radio 16 px, padding 24/20 px, separación 16 px y columnas 3/2/1 en >1200 / 641–1200 / <=640 px. Títulos 24 px/650, cuerpo 15 px, enlaces 14 px/600. Altura por contenido, sin recortes. Iconos y categorías opcionales propios de Herramientas; condiciones y suspensión de pagos conservadas.

Borde verde al pasar el puntero fino, transición de 150 ms como Home. Foco azul de 3 px con teclado. Enlace existente extendido por CSS a toda la tarjeta, sin nuevos tab stops ni JS. Movimiento reducido desactiva transiciones. No se añaden elevaciones ni desplazamientos. La Home conserva dos exchanges iniciales y el desplegable móvil.

Los selectores existentes se mapean a un único componente; las clases apple-catalog-card/grid quedan disponibles para nuevas páginas. Se aplicará a otras páginas al rediseñarlas y verificarlas, sin cambios masivos no auditados.

QA: firma de estilos y ancho comparados Home/Herramientas en 13 anchos, hover, foco y clic en el padding con registro ficticio interceptado; suites previas, texto 200%, sin JS y movimiento reducido. Datos exclusivamente sintéticos.

Las vistas raíz son autocontenidas noindex con sesión anónima simulada. Excluir de cualquier integración de producción. Pendiente CI y aprobación visual.
