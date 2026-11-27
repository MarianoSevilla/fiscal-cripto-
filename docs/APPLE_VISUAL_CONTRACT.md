# Contrato visual Apple: control de equivalencia obligatorio

Aprobación del propietario (27-11-2026): no crear variantes de componentes ya aprobados. No basta que no exista overflow; un componente puede verse bien aisladamente y no respetar el estándar.

Referencia canónica de la banda verde editorial: /como-funciona y /recursos. Home proporciona contenedor, tipografía, paleta, navegación y tokens compartidos. No modificar una referencia aprobada para hacer pasar una comparación. Conservar el contenido y las funciones de cada página.

- Contenedor de banda: ancho 100%, máximo var(--apple-max), padding horizontal var(--apple-pad).
- H1 y subtítulo: ocupan el ancho útil completo; max-width:none. No ch estrechos, balance forzado o saltos BR arbitrarios. Salto natural según resolución.
- Banda: padding vertical 40/32px desktop, 32/32px tablet, 36/24px móvil (mismos breakpoints que Cómo funciona).
- H1: mismas medidas, tipografía y margen inferior que Cómo funciona (20px desktop/tablet, 16px móvil).
- Subtítulo: mismos color, tamaño, line-height, ancho. Margen inferior cero si es el último elemento: el espacio hasta el borde inferior es el padding aprobado. Si hay CTA real, usar su separación aprobada.
- Comparar las propiedades computadas del componente nuevo con una referencia ya validada de otra familia, no solo con una página que comparte el CSS nuevo. Verificar geometría real: posiciones, anchos, separación, colores, fuentes, bordes y controles. Revisar capturas en 390, 768 y 1440 px cuando sean accesibles; probar los 13 anchos del CI y los estados interactivos relevantes.
- El breadcrumb existente es contenido de navegación y debe conservarse; no justifica un padding extra de toda la banda.
- Para otros componentes, usar los originales de Contacto, Cuenta, Dashboard, CTA y tarjetas según su función. No inventar clases estilísticas ni valores. Si no hay equivalente aprobado para un componente especializado, dejarlo sin publicar y explicar el impedimento.
- El CI requerido debe permanecer completo y añadir controles específicos, nunca sustituir una prueba existente por una más débil. No fusionar con fallos. No enviar datos reales, cambiar permisos, reactivar pagos ni modificar lógica fiscal.
- La publicación solo se considera comprobada con Railway SUCCESS y el commit esperado. No presentar capturas automáticas como revisión humana.

La suite qa_apple_hero_standard.py compara las siete guías existentes con /como-funciona. Toda nueva página editorial con banda verde debe integrarse en este control o uno equivalente contra la misma referencia, no contra una nueva variante.

### Paneles promocionales de las guías fiscales y de exchanges

Referencia vigente del propietario: Home (`#asistenciaBlock`) y Herramientas. Reutilizar `.asistencia-block`, `.asistencia-badge`, `.asistencia-bullets` y `.btn-asistencia` de landing_apple.css, sin modificar las dos páginas aprobadas. No crear una variante de tarjeta ni usar un panel vacío que solo contenga un botón. Los destinos y las atribuciones se conservan; las atribuciones editoriales quedan fuera del panel, y las acciones secundarias reutilizan el enlace existente de Home. Las tarjetas de catálogo, alertas y paneles operativos no son CTA promocionales y mantienen su función. Comparar estilos y geometría real de todos los paneles con Home en los 13 anchos; guardar capturas individuales a 390, 768 y 1440. El contenido y los saltos de línea pueden variar, no el diseño. El CI completo debe estar verde antes del despliegue.
