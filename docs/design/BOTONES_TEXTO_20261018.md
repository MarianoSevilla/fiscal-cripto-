# Etiquetas de botones: solo texto

Autorización: retirar la flecha del CTA de Exchanges y revisar la web para eliminar símbolos decorativos de los captions. Los cambios se preparan en la rama de preview; no autorizan merge ni publicación en producción.

Se revisaron 95 archivos HTML, JavaScript y CSS de static y templates. Las etiquetas afectadas se corrigen en 16 archivos fuente: administración de asesoramiento, comunicaciones y contactos; páginas editoriales/guías e índice de Exchanges; preview de Exchanges; Herramientas; Modelo 721; navegación compartida; estadísticas; plantillas Binance y Tool. El generador y la vista autocontenida de Exchanges también se actualizan.

Se eliminan flechas, pictogramas y adornos de etiquetas textuales; incluye estados dinámicos que restablecían “Generar”, “Generar informe”, “Enviar test” o la confirmación de borrado. Se retiran cuatro SVG decorativos de botones textuales de Modelo 721.

Se conservan iconos funcionales sin caption (menú, cierre, actualizar), indicadores de expansión y marcas de identidad del proveedor de acceso o exchange. Los enlaces de texto y tarjetas conservan sus indicadores de navegación; no son botones de acción. No se cambia contenido fiscal, importes, permisos, endpoints, atributos de formularios ni manejadores de eventos.

Archivos fuente afectados:

- fiscal_app_export/static/admin-asesoramiento.html
- fiscal_app_export/static/admin-comunicaciones.html
- fiscal_app_export/static/admin-contactos.html
- fiscal_app_export/static/compensar-perdidas-criptomonedas.html
- fiscal_app_export/static/exchanges.html
- fiscal_app_export/static/exchanges_apple.html
- fiscal_app_export/static/herramientas.html
- fiscal_app_export/static/metodo-fifo-criptomonedas.html
- fiscal_app_export/static/modelo721.html
- fiscal_app_export/static/nav.js
- fiscal_app_export/static/perdidas-patrimoniales-criptomonedas.html
- fiscal_app_export/static/permuta-criptomonedas-irpf.html
- fiscal_app_export/static/regla-dos-meses-criptomonedas.html
- fiscal_app_export/static/stats.html
- fiscal_app_export/templates/binance_v2.html
- fiscal_app_export/templates/tool.html

Además: scripts/build_exchanges_preview.py y exchanges-apple-preview/index.html para que reconstruir la vista no recupere la flecha ni los captions anteriores del menú.

Validación local: comparación de atributos y número de acciones frente a la base, revisión de estados dinámicos, sintaxis de nav.js y búsqueda de símbolos residuales en botones con etiqueta. La suite Required CI existente comprobará la regresión. No se accede a cuentas ni informes reales, ni se ejecutan acciones de envío o borrado.
