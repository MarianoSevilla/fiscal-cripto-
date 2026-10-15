# Home Apple: variante aislada para revisión

Base: `main@8cbb38fc96e9ba47f5e4657182c8ea4a2855a6e4`.
Estado: propuesta visual. No sustituye la Home, no se despliega y no autoriza merge.

## Alcance

- Nuevos `static/landing_apple.html`, `landing_apple.css`, `landing_apple.js`.
- Documento de revisión y pruebas de preservación/navegador.
- Una llamada adicional en `qa_responsive_layout.py` permite que el CI existente
  compruebe esta variante con las herramientas ya declaradas. No cambia workflows.
- Sin cambios a `landing.html`, `nav.css`, `nav.js`, `app.py`, rutas, pagos,
  seguridad, motor FIFO, configuración o base de datos.

## Decisiones visuales

Tema claro, tipografía de sistema sin fuentes externas, verde profundo de acción.
Mensaje principal, CTA y ejemplo ficticio al inicio; funcionamiento, informe,
exchanges, asesoramiento y equipo después; contenido SEO íntegro al final.
FAQ con detalles nativos, teclado y contenido en el HTML. Tablas del ejemplo
conservan las cinco columnas mediante scroll local. Estilos bajo `.apple-home`.

Se preservan todos los párrafos, palabras, enlaces de destino, datos estructurados,
canonical, campos y script de autenticación de la Home de referencia. Se añade
una indicación de datos ficticios y el aviso de suspensión de presupuestos/pagos
que ya rige en las páginas de asesoramiento de la base.

`noindex,nofollow` identifica la variante. No se enlaza desde navegación o sitemap.
Esto es una medida de indexación, no un control de acceso: la privacidad de la
revisión depende de mantener la rama sin despliegue y de compartir solo los
artefactos de prueba. No se crea una ruta pública ni se modifica Flask.

## Pruebas

`python -m unittest discover -s fiscal_app_export/tests -p test_home_apple.py -v`

Protege contenido, párrafos, enlaces, JSON-LD, canonical, IDs, archivo original y
script de autenticación. No importa la aplicación ni requiere Flask o DB.

El CI existente ejecuta `qa_responsive_layout.py`, que conserva la prueba original
y llama además `qa_home_apple.run_home_apple`. La ampliación comprueba 12 anchuras,
estados de navegación con roles sintéticos, acordeones, diálogo, texto 200%,
movimiento reducido, menú de altura baja y navegación sin JS. Toda petición API
se intercepta con fixtures; las escrituras y tráfico externo hacen fallar la prueba.
Capturas: `qa-artifacts/home_apple_*.png`, recogidas por el artefacto existente.

El autor debe revisar los resultados y las capturas del SHA final. Hasta entonces,
el código de un test no constituye evidencia de que haya pasado.

Pendiente de validación física Safari/iOS y lector de pantalla. No se afirma
conformidad WCAG completa ni mejora de Core Web Vitals sin mediciones.

## Revisión del propietario

Valorar color, tipografía, claridad, orden, presencia del ejemplo, confianza y
experiencia móvil. Iterar en la misma rama. La incorporación al original requiere
aprobación visual, pruebas satisfactorias y una comparación contra el `main`
vigente que preserve cambios paralelos. Publicar requiere autorización separada.
