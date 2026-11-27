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

### Tarjetas de informe FIFO de las guías de exchanges

Referencia vigente del propietario (27-11-2026): primera tarjeta de Binance, `.content-main > .asistencia-block`. La tarjeta intermedia y final de las siete guías deben compartir fondo, borde, radio, padding superior e inferior, tipografía, etiqueta verde INFORME FIFO [EXCHANGE] y estilo de beneficios del bloque validado. Conservar los dos botones existentes, destinos y la nota de supervisión de la tarjeta final; eliminar los microtextos redundantes de creación de cuenta y subida. Mantener el contenido específico de cada exchange. Comparar estilos computados directamente con la primera tarjeta en los 13 anchos, además de comparar las tarjetas intermedias entre sí y conservar capturas en 390, 768 y 1440 px. No fijar alturas; los saltos de texto y la nota de supervisión pueden variar el alto total.
