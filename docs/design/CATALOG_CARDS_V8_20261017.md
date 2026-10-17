# V8 · Home como estándar de tarjetas

Solicitud del propietario (17/10/2026): simplificar Herramientas siguiendo la estructura de las tarjetas Home. Se retiran iconos, categorías y etiquetas auxiliares de cada tarjeta. Tres elementos: h3, descripción breve y enlace. Se conserva cada destino. El primer enlace pasa de Crear cuenta a Preparar mi informe, manteniendo /signup/.

Las seis descripciones se optimizan para explicar utilidad y destino. El aviso de suspensión de presupuestos/pagos permanece dentro de la descripción de asesoramiento, visible antes de pulsar; no se elimina ni traslada a una pantalla posterior. El resto del HTML, FAQs, metadatos, footer y navegación es idéntico a V5 salvo la sección de catálogo autorizada. Fixture V5 se conserva.

El CSS compartido de Home V7 es la referencia y permanece intacto. Se elimina CSS local de iconos/metadatos y las reglas visuales redundantes de tarjetas Herramientas. Descripción sin flex-grow; enlace al pie como Home. Altura natural por contenido y texto ampliado, con alineación por fila; no se fijan alturas ni se recortan textos. Hover y foco compartidos permanecen.

QA conserva los 13 anchos y compara estilo/ancho entre páginas; comprueba que solo hay título, párrafo y enlace en cada tarjeta, sin reintroducir etiquetas. Contrato de contenido protege todo el HTML fuera del catálogo. Sin instalaciones, backend, seguridad, datos reales, pagos ni producción. Pendiente CI y revisión visual.
