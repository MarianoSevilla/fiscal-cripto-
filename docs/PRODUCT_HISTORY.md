# PRODUCT_HISTORY.md
### Historia de las decisiones de producto

Este documento recoge cronológicamente las decisiones que han marcado la evolución del producto. No es un ADR (no describe una decisión técnica puntual), no es un documento de diseño (no describe cómo se hace algo), y no es un log de commits. Es el relato de por qué el producto es como es.

Cada entrada incluye: qué ocurrió, en qué contexto, qué se decidió, por qué, y qué impacto tuvo.

---

## 2026-04-25 — Primera versión pública del sistema

**Contexto:** El repositorio arranca con los primeros uploads de código. El sistema ya incluye el motor FIFO, el clasificador de Binance y la generación de PDF. La herramienta de Binance existe como página estática en `/static/exchanges/binance.html`, servida directamente sin autenticación ni sesión de usuario.

**Decisión:** Desplegar la primera versión funcional de la herramienta fiscal de Binance en Railway.

**Motivo:** Validar el ciclo completo (CSV → FIFO → PDF) con usuarios reales antes de iterar en UX.

**Impacto:** Establece el núcleo técnico del producto: motor FIFO + clasificador por exchange + generador PDF. Este núcleo no cambia en ninguna revisión posterior — toda la evolución del producto ocurre en la capa de interfaz y de experiencia de usuario.

---

## c. 2026-05 a 2026-06 — Primeras iteraciones de la herramienta Binance

**Contexto:** La herramienta de Binance recibe sucesivas iteraciones de diseño. En algún punto de este período se construye y se descarta una versión con vídeo incrustado, una versión con selector de exchange, y una versión con los cards de benefits fuera del panel.

**Decisión: Eliminar el vídeo incrustado de YouTube antes del formulario.**
El vídeo tutorial de "cómo descargar el CSV" se incrustaba como iframe de YouTube antes del Drop Zone. Se sustituyó por un enlace de texto dentro del Drop Zone: "▶ Ver vídeo para descargar el CSV (2 min)".
*Motivo:* El iframe compite visualmente con el CTA. El usuario que ya sabe qué hacer tiene que desplazar el vídeo para llegar al formulario — la herramienta penaliza al usuario recurrente. El iframe añade dependencia de red en el camino crítico. El enlace de texto resuelve los tres problemas: disponible para quien lo necesite, invisible para quien no.

**Decisión: No añadir selector de exchange dentro de la herramienta.**
Se exploró añadir un selector ("¿Para qué exchange es este CSV?") para que una sola URL sirviera todos los exchanges. Descartado.
*Motivo:* El usuario que llega a `/binance` ya tomó esa decisión. El selector es una pregunta cuya respuesta está implícita en la URL. Además, un selector único requiere que el frontend conozca todos los parsers. La arquitectura correcta es una URL por exchange.

**Decisión: Mover los Benefits dentro del panel.**
Los cards de beneficio estaban como sección independiente bajo el panel. Se integraron dentro del panel, como bloque final tras el Config Row.
*Motivo:* Fuera del panel se perciben como marketing, no como parte de la herramienta. Dentro del panel, son parte del producto. Además, desaparecen en el Done State sin competir con el estado de éxito.

**Decisión: Igualar el ancho del Hero y el panel.**
En alguna iteración el Hero tenía un `max-width` menor que el panel. Se igualaron a `--w: 1060px`.
*Motivo:* La diferencia de anchos transmitía descuido — el encabezado y el formulario parecían piezas de páginas distintas. El ancho único convierte la página en una sola columna de peso consistente.

**Impacto acumulado:** Estas decisiones definen la filosofía de la herramienta: sin fricción innecesaria, sin elementos que compitan con el flujo, sin información que no contribuya a la tarea del usuario. Quedan documentadas en `docs/DESIGN_SYSTEM.md §12` como decisiones de diseño de referencia.

---

## 2026-06-23 — KuCoin fase 1 y Bitget multiarchivo

**Contexto:** El silo crece. KuCoin (fase 1, soporte multiarchivo) y Bitget (soporte multiarchivo para spot trading) se incorporan al sistema. Ambos usan el patrón existente `tool.html + EXCHANGE_PAGES`.

**Decisión:** Incorporar KuCoin y Bitget como nuevos exchanges usando el patrón `tool.html`.

**Motivo:** El patrón existente funciona. No hay razón en este momento para cambiarlo — el silo tiene suficientes exchanges para validar el patrón pero no los suficientes problemas acumulados para cuestionarlo.

**Impacto:** El silo llega a 10 exchanges (Bitvavo, Bit2Me, Kraken, Coinbase, Nexo, Crypto.com, Uphold, MEXC, Bitget, KuCoin) todos sobre `tool.html`. La plantilla genérica está cerca de su límite de mantenibilidad. El siguiente exchange que llegue será Binance con un rediseño, y ese proceso dejará en evidencia los límites del patrón.

---

## 2026-06-26 a 2026-06-27 — Exchange Blueprint v1: overhaul de la experiencia post-análisis

**Contexto:** La herramienta de Binance tiene un problema de UX identificado: tras generar el informe, el panel vuelve al estado inicial — Drop Zone vacío, CTA deshabilitado. El usuario no sabe si el proceso terminó. No hay una transición clara al estado de éxito. El usuario tiene que bajar la página para ver los resultados.

**Sprint: `feature/exchange-blueprint-v1`** — rama creada el 2026-06-26 con el objetivo de rediseñar el flujo de trabajo post-informe para eliminar los callejones sin salida.

**Decisión: Crear el Done State.**
Cuando el análisis termina, el panel se transforma en un estado de éxito inequívoco: ícono de check, "Tu informe fiscal ya está listo", dos acciones claras ("Nuevo análisis" y "Analizar otro exchange →").
*Motivo:* Sin el Done State, el panel queda en estado ambiguo — exactamente igual que al principio, pero el análisis ya terminó. La ambigüedad genera ansiedad. El Done State resuelve el problema de raíz: el panel cambia visiblemente, el usuario sabe exactamente qué pasó.

**Decisión: Añadir instrucciones post-análisis (bloque "¿Y ahora qué?").**
Tras generar el informe, aparece un bloque que explica al usuario qué hacer con el PDF: qué casillas de la renta rellenar, cómo usarlo junto al historial del exchange.
*Motivo:* El usuario que acaba de descargar un PDF fiscal no necesariamente sabe cómo usarlo en la declaración. Este bloque elimina esa incertidumbre sin salir de la página.

**Decisión: Botón "Nuevo análisis" en el Done State.**
Desde el Done State, el usuario puede volver al estado inicial con un clic, sin recargar la página.
*Motivo:* El usuario recurrente (que analiza varios ejercicios) necesita repetir el flujo sin fricción. El botón resetea el formulario limpiamente.

**Resultado del sprint:** `binance_v2.html` se crea como nueva plantilla de referencia, incorporando todo lo anterior más el rediseño visual completo. Se mergea a `main` el 2026-06-27.

**Impacto:** El Exchange Blueprint queda establecido como el patrón de experiencia para cualquier herramienta nueva. El concepto "exchange blueprint" nombra formalmente el estándar.

---

## 2026-06-28 — Design System v1: formalización del estándar visual

**Contexto:** `binance_v2.html` existe y está validada. Es la primera implementación de referencia completa. Las decisiones de diseño acumuladas en los meses anteriores están en el código pero no documentadas.

**Decisión: Crear `docs/DESIGN_SYSTEM.md`.**
Documento oficial del estándar visual y de experiencia de usuario de todas las herramientas del silo. Destila todos los tokens, componentes, estados, reglas, anti-patrones y decisiones de diseño desde `binance_v2.html`.
*Motivo:* Sin documentación, cualquier exchange nuevo repetiría las mismas decisiones (y los mismos errores) desde cero. El Design System elimina esa deuda de conocimiento.

**Alcance del documento:** Filosofía del producto, arquitectura de página, sistema de grid, tipografía, color, 14 componentes, 8 estados, 4 breakpoints responsive, 9 reglas de accesibilidad, 14 anti-patrones documentados, 9 decisiones de diseño razonadas, tabla de adaptación por exchange, checklist de validación, proceso de evolución del sistema.

**Impacto:** El silo tiene ahora una fuente única de verdad para el diseño. Un desarrollador nuevo (o una IA colaborando en el proyecto) puede construir un exchange nuevo sin tomar ninguna decisión de diseño no resuelta.

---

## 2026-06-28 — Validación visual de `binance_v2.html` y ajustes de espaciado

**Contexto:** `binance_v2.html` existe pero sus valores de espaciado venían de la implementación inicial, no de una validación visual deliberada.

**Proceso:** Metodología de Product Designer — un solo ajuste cada vez, revisión visual, aprobación, siguiente ajuste. Sin cambios simultáneos, sin justificación matemática.

**Decisión: Tres ajustes de espaciado aprobados.**
- `hero padding-top`: 60px → 72px. Más espacio sobre el hero, separación más generosa del nav.
- `trust-row margin-top`: 20px → 30px. Más separación entre el subtítulo y la banda de garantías.
- `pre-note margin-top`: 24px → 8px. La línea operativa se acerca al panel — reduce la distancia perceptiva entre el mensaje y el área de trabajo.

**Motivo:** Los valores originales eran funcionales pero no óptimos visualmente. La iteración con revisión visual produce resultados que el cálculo matemático no puede anticipar.

**Impacto:** Los valores aprobados quedan en `binance_v2.html` y documentados en `DESIGN_SYSTEM.md §3`. Son los valores de referencia para cualquier exchange que siga el nuevo patrón.

---

## 2026-06-28 — `/binance` unificado a `binance_v2.html`

**Contexto:** Existían dos rutas que servían la nueva interfaz de Binance: `/binance` (con `tool.html` y variables de `EXCHANGE_PAGES`) y `/binance-v2` (con `binance_v2.html` standalone). Tras la validación visual y funcional completa de `/binance-v2`, la ruta `/binance` seguía sirviendo la interfaz legacy.

**Decisión:** Cambiar una línea en `app.py` para que `/binance` sirva `binance_v2.html` en lugar de `tool.html`. `/binance-v2` se mantiene temporalmente como ruta de respaldo.

**Motivo:** La validación estaba aprobada. La URL de producción es `/binance`, no `/binance-v2`. El usuario que llega desde buscadores o bookmarks llega a `/binance`.

**Impacto:** `/binance` en producción sirve el nuevo diseño. La migración afecta a cero líneas del motor FIFO, parsers, endpoints o JavaScript de lógica funcional. El cambio es de una línea.

---

## 2026-06-28 — Adopción del patrón de plantillas standalone por exchange

**Contexto:** La unificación de `/binance` pone en evidencia la diferencia entre el patrón antiguo (`tool.html + EXCHANGE_PAGES`) y el nuevo (`binance_v2.html` standalone). El proceso de diseño y validación de Binance fue posible porque su plantilla era independiente — cualquier cambio en ella no afectaba a los otros exchanges.

**Decisión:** El patrón standalone se convierte en el estándar oficial para cualquier exchange nuevo. `tool.html` se mantiene para los 10 exchanges existentes como patrón legacy.

**Principio que formaliza esta decisión:** *Cada exchange es un producto, no una configuración.* El Hero, el tutorial, el copy de confianza, los mensajes de error y las instrucciones post-análisis necesitan hablar al usuario específico de ese exchange con precisión. Un template genérico puede hacer eso hasta cierto punto; una plantilla standalone lo hace sin límites.

**Documentación:** `docs/decisions/ADR-0002-exchange-template-standalone.md` y `docs/EXCHANGE_IMPLEMENTATION_GUIDE.md`.

**Impacto:** El silo tiene ahora una arquitectura dual (legacy + nuevo estándar) con un camino claro hacia adelante. Cualquier exchange nuevo sigue el patrón standalone desde el primer día.

---

## Cómo mantener este documento

Este documento se actualiza cuando:
- Se toma una decisión de producto que cambia la dirección del sistema o del silo.
- Se incorpora un exchange con características que generan nuevas decisiones de diseño o arquitectura.
- Una decisión documentada se revierte o evoluciona.

No se actualiza por: cambios de copy menores, correcciones de bugs, ajustes visuales que no cambian el sistema, incorporación de un exchange que sigue el patrón sin excepciones.

Las decisiones técnicas puntuales con contexto, alternativas y consecuencias pertenecen a `docs/decisions/` (ADRs). Este documento recoge la narrativa — el hilo conductor que conecta esas decisiones.
