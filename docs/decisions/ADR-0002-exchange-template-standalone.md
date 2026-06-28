# ADR-0002 — Plantillas HTML standalone por exchange como nuevo estándar

**Estado:** Aceptado
**Fecha:** 2026-06-28
**Autores:** Mariano Sevilla Trujillo
**Reemplaza:** patrón `tool.html + EXCHANGE_PAGES` para exchanges nuevos
**Referenciado desde:** `docs/ARCHITECTURE.md §18`, `docs/EXCHANGE_IMPLEMENTATION_GUIDE.md`

---

## Contexto

El silo de herramientas de exchanges de marianosevilla.com tenía un único patrón para servir las páginas de cada exchange: una ruta Flask que llama a `render_template("tool.html", **EXCHANGE_PAGES["[exchange]"])`.

`tool.html` es una plantilla Jinja2 genérica que recibe variables del servidor (`{{ exchange }}`, `{{ title }}`, `{{ trust_items }}`, etc.) desde el diccionario `EXCHANGE_PAGES` definido en `app.py`.

Este patrón tiene tres problemas que se hicieron evidentes durante el desarrollo de la herramienta de Binance:

**Problema 1: el template genérico acumula condicionales.**
Cuando los exchanges difieren en copy, estructura de errores, instrucciones post-análisis o matices de UX, la única forma de manejarlos dentro de `tool.html` es añadir `{% if exchange == 'binance' %}` o pasar variables adicionales a `EXCHANGE_PAGES`. A medida que el número de exchanges crece, `tool.html` se convierte en un template lleno de condicionales, difícil de leer y de modificar sin riesgo de romper otro exchange.

**Problema 2: el template genérico frena la iteración de diseño.**
Durante el proceso de diseño y validación de la herramienta de Binance, cada cambio en el HTML requería verificar que no afectara a los demás exchanges que comparten el template. El coste de validación crece linealmente con el número de exchanges. Una plantilla standalone es autocontenida — cualquier cambio en ella solo afecta a ese exchange.

**Problema 3: el template genérico no puede divergir de forma controlada.**
El Design System admite que exchanges distintos tengan variaciones menores en copy, instrucciones post-análisis, o mensajes de error. Con `tool.html`, estas variaciones requieren lógica condicional en el template o más variables en `EXCHANGE_PAGES`. Con una plantilla standalone, la variación está localizada en el HTML del exchange correspondiente sin contaminar el genérico.

---

## Principio subyacente: cada exchange es un producto, no una configuración

Los tres problemas técnicos anteriores son síntomas de un problema más profundo: el patrón `tool.html + EXCHANGE_PAGES` trata a cada exchange como una *configuración* de una herramienta genérica. Esta visión es incorrecta.

**Un exchange no es una configuración. Es un producto.**

El usuario que llega a `/binance` y el usuario que llega a `/kraken` tienen perfiles distintos, preguntas distintas y relaciones distintas con sus datos. No es el mismo usuario con un CSV diferente.

**El Hero necesita hablar al usuario específico de ese exchange.**
"Genera tu informe fiscal de Binance para Hacienda" no es una frase con el nombre del exchange como variable intercambiable. Es una frase escrita para el usuario de Binance: alguien que ha exportado un "Transaction History", que probablemente ya declaró en años anteriores, y que reconoce inmediatamente qué archivo tiene que subir. El usuario de Kraken descargó "Ledgers", no "Transaction History", y su relación con ese archivo es diferente. El Hero que le habla tiene que saber eso.

**El tutorial es por exchange, no por herramienta.**
El vídeo "cómo descargar el CSV en 2 minutos" muestra una interfaz de exchange concreta — Binance tiene una, Kraken tiene otra, KuCoin otra. No existe un tutorial válido para todos los exchanges. El link del Drop Zone apunta a una URL específica del exchange, no a un tutorial genérico.

**El copy de confianza responde a las objeciones específicas de ese exchange.**
"Compatible con el CSV oficial de Binance" tiene significado porque hay usuarios que intentan subir un CSV de Binance antiguo, o el CSV equivocado, y el Trust Item les dice exactamente que sí, este es el archivo correcto. Ese mensaje necesita nombrar al exchange — no puede ser "Compatible con el CSV oficial de tu exchange".

**Los mensajes de error son específicos del exchange.**
Un error de columnas incorrectas en Binance tiene una explicación diferente a un error de columnas incorrectas en Kraken. Los pasos para resolverlo son distintos: la ruta de exportación en Binance no es la misma que en Kraken. Un template genérico que sirve mensajes de error parametrizados nunca puede ser tan preciso como uno que conoce exactamente qué CSV espera y exactamente qué le dice al usuario cuando no coincide.

**Las instrucciones post-análisis son específicas del exchange y del contexto fiscal.**
Tras generar el informe de Binance, las instrucciones le dicen al usuario exactamente qué casillas de la renta rellenar y cómo usar el PDF junto al Transaction History. Ese texto está escrito para alguien que tiene un PDF de Binance en su escritorio. El mismo texto con el nombre del exchange sustituido no funciona — el contexto fiscal y operativo es distinto para cada herramienta.

---

La conclusión de este principio es que la arquitectura correcta para un silo de herramientas de exchanges no es *una herramienta configurable*, sino *un Design System compartido + herramientas independientes*. El Design System garantiza la coherencia visual, de comportamiento y de vocabulario. Las herramientas independientes garantizan que cada exchange puede hablar a sus usuarios con precisión.

`tool.html` resuelve el primer problema pero no el segundo. Una plantilla standalone con un Design System sólido resuelve ambos.

---

## Decisión

**A partir del 2026-06-28, cada exchange nuevo recibe su propia plantilla HTML standalone** (`[exchange]_v1.html`), servida por una ruta Flask que llama directamente a `render_template("[exchange]_v1.html")` sin variables Jinja2.

La autenticación y el contexto del usuario se obtienen del lado del cliente mediante `GET /api/me` al cargar la página — el mismo mecanismo que usa `binance_v2.html`. Las plantillas no dependen de variables del servidor.

La plantilla de referencia para todos los exchanges nuevos es `fiscal_app_export/templates/binance_v2.html`. El proceso de creación está documentado en `docs/EXCHANGE_IMPLEMENTATION_GUIDE.md`.

El patrón `tool.html + EXCHANGE_PAGES` se mantiene para los exchanges que ya lo usan (Bitvavo, Bit2Me, Kraken, Coinbase, Nexo, Crypto.com, Uphold, MEXC, Bitget, KuCoin). No se migran salvo que haya una razón de producto que lo justifique.

---

## Alternativas consideradas

**Mantener `tool.html` y añadir variables para cada nuevo exchange.**
Descartado. Agrava el Problema 1 y el Problema 3. La complejidad de `tool.html` crece con cada exchange; la capacidad de iterar por exchange decrece.

**Migrar todos los exchanges existentes a plantillas standalone.**
Descartado como alcance de esta decisión. Los exchanges en `tool.html` funcionan en producción. El coste de migrarlos (crear el HTML standalone, probar el flujo completo, desplegar) no está justificado en este momento sin una razón de producto. Pueden migrarse individualmente si hay una razón concreta — por ejemplo, para aplicar un rediseño o corregir comportamientos específicos del exchange.

**Un template por exchange generado dinámicamente (templating con Jinja2 y macros).**
Descartado. El overhead de mantener una capa de generación de templates supera el beneficio en este volumen. Los templates standalone son directamente legibles y modificables.

---

## Consecuencias

**Positivas:**
- Cada exchange puede iterar de forma independiente sin riesgo de romper otros.
- Añadir un exchange nuevo es predecible: duplicar `binance_v2.html`, modificar la lista de elementos del `DESIGN_SYSTEM.md §13`, añadir la ruta en `app.py`.
- La validación antes de publicar un exchange nuevo es autocontenida: el checklist de `DESIGN_SYSTEM.md §14` aplica a la plantilla sin tener que verificar efectos en `tool.html`.
- El Design System puede evolucionar componente a componente — un nuevo componente aprobado se añade al estándar y se incorpora en los exchanges nuevos; los exchanges legacy en `tool.html` pueden actualizarse en su propio ciclo.

**Negativas / compensaciones:**
- El HTML de cada exchange ocupa espacio propio en el repositorio. Con 10+ exchanges, son 10+ ficheros HTML de ~1600 líneas cada uno.
- Un cambio que aplica a todos los exchanges (por ejemplo, actualizar el footer o un componente compartido) debe propagarse a cada plantilla standalone individualmente. Con `tool.html`, ese cambio se hace una vez.
- Los exchanges en `tool.html` y los exchanges en plantillas standalone tienen distintos flujos de validación. Quien trabaje en el sistema necesita saber cuál patrón usa cada exchange.

La segunda compensación (propagación de cambios globales) es la más relevante a largo plazo. La posición adoptada es que la frecuencia de cambios globales es baja — el Design System es estable — y que la independencia de iteración por exchange tiene más valor en el ciclo actual del producto que la conveniencia de cambios globales en un solo fichero.

---

## Estado de implementación

- **Binance** (`/binance`): migrado a `binance_v2.html` el 2026-06-28. Primera implementación del nuevo patrón.
- **Resto de exchanges** (Bitvavo, Bit2Me, Kraken, Coinbase, Nexo, Crypto.com, Uphold, MEXC, Bitget, KuCoin): siguen usando `tool.html`. Patrón legacy vigente hasta que se decida migrarlos.
- **Exchanges futuros:** deben usar el patrón standalone desde el primer día.
