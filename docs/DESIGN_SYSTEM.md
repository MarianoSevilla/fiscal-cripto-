# Exchange Tool Design System v1

**Documento oficial del estándar visual y de experiencia de usuario**
de todas las herramientas de marianosevilla.com.

Referencia de implementación: `/fiscal_app_export/templates/binance_v2.html`
Fecha de creación: 2026-06-28

---

## Principios inmutables

Estas reglas no son preferencias de diseño. Son invariantes del producto. No pueden romperse en ninguna herramienta, en ninguna versión, por ninguna razón de implementación. Si una decisión técnica entra en conflicto con alguno de estos principios, el conflicto se resuelve cambiando la decisión técnica.

**1. Hero y panel comparten siempre el mismo ancho.**
La coherencia visual entre el encabezado y el área de trabajo es una señal de calidad y de intención. Un Hero más estrecho que el panel transmite descuido. Un Hero más ancho que el panel fragmenta la composición. El ancho único (`--w: 1060px`) convierte la página en una sola columna de peso consistente.

**2. Existe un único CTA principal activo en cada momento.**
El usuario nunca debe elegir entre dos acciones primarias. Si hay dos caminos posibles, uno de ellos es secundario y debe parecerlo — visualmente más pequeño, con menos peso, con un rol diferente. La decisión sobre qué hacer a continuación siempre la toma el producto, no el usuario.

**3. El usuario siempre sabe cuál es la siguiente acción.**
La interfaz nunca deja al usuario en un estado sin salida clara. Si no puede hacer nada, hay un mensaje que explica por qué y qué tiene que cambiar. Si puede hacer algo, hay un elemento prominente que lo invita. El estado de la interfaz siempre es legible.

**4. El Hero elimina la incertidumbre antes de pedir cualquier acción.**
El usuario no sube ningún archivo que no entienda. Los mensajes de confianza (Trust Row) preceden siempre al Drop Zone. La Pre-note precede siempre al panel. Antes de llegar al área de trabajo, el usuario ya sabe qué necesita, qué va a obtener, por qué es legal, y cuánto va a tardar.

**5. La lógica de negocio nunca depende de la interfaz.**
El motor fiscal, los parsers de CSV y la lógica de cálculo son módulos independientes del HTML y el CSS. Una herramienta puede rediseñarse completamente — incluso reescribirse — sin que una sola línea del motor fiscal cambie. El acoplamiento en la dirección inversa tampoco existe: el motor no lee ni interpreta la interfaz.

**6. Tras generar un informe nunca puede quedar un estado ambiguo.**
El panel se transforma en un estado de éxito inequívoco. El PDF está disponible. Hay exactamente dos salidas: nuevo análisis en la misma herramienta, o navegar a otro exchange. El usuario nunca tiene que preguntarse si el proceso terminó.

**7. Todas las herramientas del silo comparten la misma arquitectura de página.**
El usuario que usa Binance y después accede a Kraken no tiene que aprender nada nuevo. La estructura, el comportamiento y el vocabulario visual son idénticos. La única diferencia está en el copy específico del exchange y en el parser del backend.

**8. El footer es único para todo el sitio.**
No existen footers por herramienta. El pie de página es un elemento de identidad del sitio, no de la herramienta. Cualquier cambio en el footer se aplica a todo el sitio simultáneamente.

**9. Los tokens de color y tipografía son la identidad visual del producto.**
`--accent: #00C896` y la pareja Syne + DM Sans no son decisiones técnicas de implementación — son la marca. No se sustituyen por conveniencia ni por preferencia personal. Si hay una razón suficiente para evolucionar la identidad, el cambio se documenta aquí y se aplica a todas las herramientas.

**10. El usuario nunca toma decisiones innecesarias.**
El método de cálculo, el formato del informe, la estructura fiscal — ya están decididos. El usuario solo toma dos decisiones: su archivo y su ejercicio fiscal. Todo lo demás está resuelto por el producto.

**11. Los componentes aprobados no se rediseñan, se reutilizan.**
Cada exchange nuevo incorpora el sistema existente. Un componente solo evoluciona cuando hay una razón de producto documentada, y el cambio se aplica a todas las herramientas simultáneamente. El coste de rediseñar es siempre mayor que el de adaptar.

**12. La interfaz habla el idioma del usuario, no del sistema.**
Los nombres internos de los formatos de exportación, los identificadores técnicos y la terminología interna del exchange nunca aparecen en la interfaz sin traducción al lenguaje del usuario. "CSV de Binance" en lugar de "Transaction History". "Ejercicio fiscal" en lugar de "año del CSV".

---

## Índice

1. [Filosofía del producto](#1-filosofía-del-producto)
2. [Arquitectura de la página](#2-arquitectura-de-la-página)
3. [Sistema de grid](#3-sistema-de-grid)
4. [Sistema tipográfico](#4-sistema-tipográfico)
5. [Sistema de color](#5-sistema-de-color)
6. [Componentes](#6-componentes)
7. [Estados](#7-estados)
8. [Responsive](#8-responsive)
9. [Accesibilidad](#9-accesibilidad)
10. [Reglas de consistencia](#10-reglas-de-consistencia)
11. [Anti-patrones](#11-anti-patrones)
12. [Decisiones de diseño](#12-decisiones-de-diseño)
13. [Adaptación a otros exchanges](#13-adaptación-a-otros-exchanges)
14. [Checklist de validación](#14-checklist-de-validación)
15. [Evolución del Design System](#15-evolución-del-design-system)

---

## 1. Filosofía del producto

### Qué queremos que sienta el usuario

El usuario llega con una tarea concreta y un cierto grado de ansiedad: tiene que declarar criptomonedas, no sabe exactamente cómo, y la fecha de la declaración se acerca. La herramienta debe hacerle sentir **competente y en control** desde el primer segundo. No debe sentir que está usando software complejo — debe sentir que alguien ya resolvió el problema por él y solo tiene que seguir un camino.

La emoción objetivo al salir de la página: *"Esto ha sido más fácil de lo que pensaba."*

### Qué decisiones debe tomar el usuario

El flujo está diseñado para que el usuario tome exactamente tres decisiones:

1. Subir su archivo CSV.
2. Seleccionar el ejercicio fiscal.
3. Pulsar el botón de generar.

Todo lo demás — el método de cálculo, la estructura del informe, las casillas del IRPF — ya está resuelto. El usuario no elige, el producto decide.

### Qué incertidumbres eliminamos

Antes de que el usuario suba el archivo, ya hemos respondido estas preguntas:

- ¿Este archivo es el correcto? (Trust row: "Compatible con el CSV oficial de Binance")
- ¿Qué voy a obtener exactamente? (Subtítulo + benefits)
- ¿Es legal el método de cálculo? (Trust row: "Método FIFO conforme al Art. 37.2 LIRPF")
- ¿Mis datos están seguros? (Trust row: "El archivo nunca se almacena")
- ¿Cuánto tiempo va a tardar? (Pre-note: "El proceso tarda menos de un minuto")

### Principios de UX

**Progresión clara.** La página se lee de arriba a abajo como una secuencia de pasos: entiendo qué es → confío en el producto → subo el archivo → genero el informe → descargo el PDF.

**Un solo CTA activo en cada momento.** En ningún estado de la interfaz existen dos botones principales simultáneos compitiendo por la atención del usuario.

**El panel es el centro de gravedad.** Todo lo que ocurre en la herramienta — subida, configuración, estado, resultado — ocurre dentro o en relación directa con el panel principal. La página no tiene secciones secundarias que compitan.

**Los mensajes de confianza preceden siempre al área de subida.** El usuario nunca llega al Drop Zone sin haber visto primero por qué puede confiar en el proceso.

**El usuario siempre sabe cuál es la siguiente acción.** Tras generar el informe, el panel se transforma en un estado de éxito que muestra exactamente qué hacer a continuación.

**La lógica de negocio nunca es visible para el usuario.** Los nombres internos de los formatos de exportación, los identificadores técnicos, y la terminología del exchange nunca aparecen en la interfaz tal como los define el exchange. Se usa siempre lenguaje orientado al usuario.

---

## 2. Arquitectura de la página

La página se estructura en bloques verticales. El orden es invariable.

### Nav

Barra de navegación del sitio, proporcionada por `nav.css` + `nav.js`. Externa a la herramienta, uniforme en todo el sitio. No se modifica por herramienta.

### Hero

**Función:** Primera impresión. Establece qué hace la herramienta, para qué exchange, y por qué es fiable. No vende — informa. El usuario debe entender en menos de tres segundos si esta herramienta es para él.

**Contenido:**
- H1: nombre de la acción + nombre del exchange + destino fiscal. Tres líneas con `<br>` explícitos.
- Subtítulo: qué hay que hacer → qué se obtiene. Una sola frase, sin jerga técnica.
- Trust Row: cuatro señales de confianza en una línea horizontal.

### Trust Row

**Función:** Eliminar las cuatro objeciones principales antes de que el usuario llegue al panel. Siempre visible, siempre antes del Drop Zone.

**Contenido fijo por herramienta (adaptar copy, no estructura):**
1. Compatibilidad con el CSV del exchange.
2. Tipo de informe generado.
3. Marco legal del método de cálculo.
4. Privacidad: el archivo no se almacena.

### Pre-note

**Función:** Última señal de baja fricción antes del panel. Responde a la pregunta implícita "¿es esto complicado?".

**Copy estándar:** "Solo necesitas un archivo · El proceso tarda menos de un minuto"

Este bloque es un separador visual que también comunica. Es obligatorio.

### Work Zone (panel principal)

**Función:** Todo el trabajo ocurre aquí. El panel es el único elemento interactivo de peso en la página.

**Estructura interna del panel (orden fijo):**

```
┌─────────────────────────────────────┐
│  Drop Area (padding 32px)           │
│  ┌─────────────────────────────┐   │
│  │   Drop Zone (272px alto)    │   │
│  └─────────────────────────────┘   │
├─────────────────────────────────────┤  ← Separator
│  Config Row (padding 20px 32px)     │
│  [Nombre] [Chips de año] [CTA]      │
├─────────────────────────────────────┤  ← Separator
│  Benefits (grid 4 columnas)         │
└─────────────────────────────────────┘
```

Cuando el trabajo está completo, Drop Area + Separator + Config + Benefits desaparecen, y se muestra el Done State dentro del mismo panel.

### Panel Meta

**Función:** Información contextual que aparece debajo del panel. Indica el archivo seleccionado y, tras el análisis, el botón "Nuevo análisis".

No es parte del panel — está fuera, debajo, en texto pequeño.

### Instrucciones Post-análisis

**Función:** Contexto fiscal accionable tras la generación. Aparece solo después de generar el informe. Explica exactamente qué hacer con el PDF generado: qué casillas rellenar, cómo compartirlo con el gestor.

### Resultados

**Función:** Mostrar el desglose numérico del análisis. Aparece debajo del panel, separado estructuralmente. Incluye: KPI grid, tabla de operaciones con tabs, y botón de descarga del PDF.

Es una sección técnica, no de marketing. El usuario que llega aquí ya tomó su decisión.

### Footer

**Función:** Información legal y navegación secundaria. Uniforme en todo el sitio.

---

## 3. Sistema de grid

### Ancho máximo y contenedor

```css
--w: 1060px
```

El contenedor principal (`.page`) y el contenedor de resultados (`.results-wrap`) comparten exactamente el mismo `max-width`. El Hero, el panel y los resultados siempre están alineados.

```css
.page        { max-width: 1060px; margin: 0 auto; padding: 0 20px 56px; }
.results-wrap{ max-width: 1060px; margin: 0 auto; padding: 0 20px 6rem; }
```

**Regla crítica:** el Hero y el panel comparten siempre el mismo ancho máximo. Nunca un Hero más estrecho que el panel, ni viceversa.

### Padding horizontal

| Breakpoint | Padding horizontal |
|---|---|
| Desktop (> 768px) | 20px |
| Tablet / Mobile (≤ 768px) | 16px |

### Separación vertical entre bloques

| Espacio | Valor |
|---|---|
| Hero completo: arriba / abajo | 72px / 32px |
| Pre-note margin-top | 8px |
| Pre-note margin-bottom (al panel) | 10px |
| Panel meta margin-top | 0.65rem |
| Padding inferior de página | 56px |

### Grid de Benefits (dentro del panel)

```css
grid-template-columns: repeat(4, 1fr);
gap: 0 1px;
background: rgba(255,255,255,0.036); /* el gap visible es el fondo transparente */
```

Los separadores entre columnas son el fondo del grid visible a través del gap de 1px. No son bordes — es una separación visual de bajo contraste.

### Grid de KPIs (resultados)

```css
grid-template-columns: repeat(4, 1fr);
gap: 1px;
border-radius: 12px;
```

---

## 4. Sistema tipográfico

### Familias

```css
--font-display: 'Syne', sans-serif;      /* H1, CTAs, headings de peso */
--font-body:    'DM Sans', sans-serif;   /* todo el texto operacional */
--font-mono:    'SF Mono', 'Fira Code', monospace; /* datos numéricos, tablas, fechas */
```

**Regla de uso:**
- `Syne` se reserva para texto de alto impacto: H1, botón CTA principal, headings de resultados, Done Title. Nunca para texto corrido.
- `DM Sans` es la fuente de trabajo. Todo lo que el usuario lee para operar la herramienta.
- `SF Mono / Fira Code` para datos: cantidades, fechas en tablas, etiquetas de datos (KPI labels, year-bar-label).

### Escala tipográfica

| Nivel | Familia | Peso | Tamaño | Line-height | Letter-spacing | Color |
|---|---|---|---|---|---|---|
| H1 | Syne | 800 | 64px | 1.05 | -0.038em | `--text` |
| Hero subtitle | DM Sans | 400 | 16px | 1.65 | — | `--sub` |
| Trust item | DM Sans | 400 | 12.5px | — | — | `--muted` |
| Pre-note | DM Sans | 400 | 12.5px | — | 0.005em | `--muted` |
| Drop Zone primary | DM Sans | 500 | 17px | 1.5 | — | `--text` |
| Drop Zone hint | DM Sans | 400 | 13.5px | 1.5 | — | `--sub` |
| Drop Zone tutorial | DM Sans | 500 | 13px | — | — | `--accent` |
| Name input | DM Sans | 400 | 14px | — | — | `--text` |
| Year chip | DM Sans | 500 | 13px | — | — | `--muted` / `--accent` |
| CTA button | Syne | 700 | 15px | — | 0.01em | #03110a |
| Benefit title | DM Sans | 600 | 12.5px | 1.4 | — | `--sub` |
| Benefit desc | DM Sans | 400 | 11.5px | 1.52 | — | #a8a49d |
| Results heading | Syne | 700 | clamp(1.1rem, 2.5vw, 1.4rem) | — | -0.02em | `--text` |
| KPI label | DM Sans | 500 | 10px | — | 0.1em | `--muted` |
| KPI value | Syne | 800 | clamp(1rem, 2.2vw, 1.4rem) | — | -0.03em | verde / rojo |
| Table header | DM Sans | 500 | 10px | — | 0.08em | `--muted` |
| Table cell | SF Mono | 400 | 12px | — | — | `--text` |
| Done title | Syne | 700 | 20px | — | -0.02em | `--text` |
| Done subtitle | DM Sans | 400 | 14px | — | — | `--muted` |
| Done button | DM Sans | 500 | 14px | — | — | `--text` |
| Footer | DM Sans | 400 | 12.5px | — | — | `--muted` |

### Pesos utilizados

`DM Sans`: 400, 500, 600
`Syne`: 700, 800

No se usa ningún otro peso. No se importan pesos que no estén en esta lista.

### Base tipográfica del documento

```css
body {
  font-family: var(--font-body);
  font-size: 16px;
  line-height: 1.6;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}
```

---

## 5. Sistema de color

### Tokens principales

```css
/* Fondos */
--bg:       #080c17;   /* fondo de página — azul oscuro profundo */
--surface:  #0e0e0e;   /* superficie del panel */
--surface2: #1a1a1a;   /* superficie secundaria (inputs activos, tab-content) */

/* Texto */
--text:     #F2EFE9;   /* texto principal — blanco cálido */
--sub:      #BFBBB3;   /* texto secundario — gris claro */
--muted:    #969189;   /* texto terciario — gris medio */
--dim:      #67645E;   /* texto muy atenuado — placeholders */

/* Acento principal */
--accent:     #00C896;              /* verde menta — acción, éxito, confianza */
--accent-dim: rgba(0,200,150,0.12); /* fondo de chips activos, hover de badge */

/* Colores semánticos */
--gold:    #F0B90B;              /* advertencias, coste cero */
--red:     #e24b4a;              /* errores, pérdidas */
--red-dim: rgba(226,75,74,0.1); /* fondo de estados de error */
```

### Bordes

```css
--border:       rgba(255,255,255,0.09);  /* borde estándar — muy sutil */
--border-hi:    rgba(255,255,255,0.12);  /* borde del panel principal */
--border-hover: rgba(255,255,255,0.18);  /* borde en hover */
```

Los bordes son siempre blancos con baja opacidad sobre fondo oscuro. Nunca colores opacos para bordes.

### Radii

```css
--radius: 14px;   /* panel exterior, empty-state, error-state */
--r-in:   10px;   /* drop zone, elementos interiores del panel */
--r-sm:    8px;   /* inputs, CTA, botones secundarios, tab-btn */
```

En mobile (≤ 768px): `--radius: 12px`, `--r-in: 8px`.

### Estados de color

| Estado | Color de acento | Fondo | Borde |
|---|---|---|---|
| Normal | — | `--surface` | `--border-hi` |
| Drag over | `--accent` (0.4 opacidad) | rgba(0,200,150,0.06) | 1.5px solid rgba(0,200,150,0.4) |
| Error zone | `--red` (0.35 opacidad) | rgba(226,75,74,0.05) | 1.5px solid rgba(226,75,74,0.35) |
| Chip activo (año) | `--accent` | `--accent-dim` | `--accent` |
| Chip "Todos" activo | #0a0a0a | `--accent` | `--accent` |
| CTA habilitado | #03110a (texto) | linear-gradient(135deg, #00D8A7, #00BE8D) | glow accent |
| CTA deshabilitado | rgba(150,145,137,0.38) | rgba(255,255,255,0.04) | rgba(255,255,255,0.08) |
| Input focus | — | rgba(255,255,255,0.055) | rgba(0,200,150,0.4) |
| Ganancia | `--accent` | — | — |
| Pérdida | `--red` | — | — |
| Advertencia | `--gold` | rgba(240,185,11,0.07) | rgba(240,185,11,0.25) |

### Fondos especiales del cuerpo

El `body` tiene dos capas de fondo sobre `--bg`:

```css
background-image:
  radial-gradient(ellipse 1400px 560px at 50% -40px,
    rgba(0,200,150,0.058) 0%, transparent 60%),      /* halo verde sutil desde arriba */
  url("data:image/svg+xml,...");                       /* textura de puntos — 28px, opacidad 0.02 */
```

El panel tiene además un **aura** (`.zone-wrap::before`): radial gradient verde centrado detrás del panel, `rgba(0,200,150,0.078)`.

### Sombras del panel

```css
box-shadow:
  inset 0 1px 0 rgba(255,255,255,0.07),   /* borde superior interior iluminado */
  0 10px 50px rgba(0,0,0,0.58),            /* sombra de profundidad */
  0 2px 8px rgba(0,0,0,0.52),             /* sombra próxima */
  0 0 0 1px rgba(0,0,0,0.32);            /* halo negro exterior */
```

### Sombra y glow del CTA habilitado

```css
box-shadow:
  0 0 0 1px rgba(0,200,150,0.25),    /* anillo exterior */
  0 0 30px rgba(0,200,150,0.35),     /* glow ambiente */
  0 0 60px rgba(0,200,150,0.13),     /* glow lejano */
  0 2px 8px rgba(0,0,0,0.48);       /* sombra de elevación */
```

En hover, los valores de glow aumentan (40px / 45%, 80px / 18%) y el botón sube `translateY(-1px)`.

---

## 6. Componentes

### 6.1 Hero H1

**Finalidad:** Comunicar en una sola mirada qué hace la herramienta y para qué exchange.

**Anatomía:**
- Tres líneas de texto separadas por `<br>` explícitos.
- Línea 3: nombre del exchange en `<span class="h-accent">` → color `--accent`.
- La distribución de líneas es una decisión deliberada de diseño, no el resultado del wrapping natural.

**Medidas:**
- Syne 800, 64px, letter-spacing: -0.038em, line-height: 1.05.
- margin-bottom: 14px.

**Regla:** Los `<br>` son invariables. Cualquier cambio de copy debe verificar que la distribución de líneas sigue siendo correcta.

---

### 6.2 Trust Item

**Finalidad:** Eliminar una objeción específica del usuario con un ícono + texto en una línea.

**Anatomía:**
```
[ícono SVG 13×13 — color: --accent, opacity: 0.9] [texto — 12.5px, --muted]
```

**Contenedor (Trust Row):**
```css
display: flex; align-items: center;
gap: 20px; flex-wrap: wrap;
margin-top: 30px;
```

**Ícono:** SVG inline, 13×13px, `stroke="currentColor"`, stroke-width 1.25. Nunca iconos de fuentes ni imágenes externas.

**Regla:** Siempre cuatro Trust Items. Los iconos son distintos para cada mensaje.

---

### 6.3 Drop Zone

**Finalidad:** Área de subida de archivos. Acepta arrastre (drag & drop) y clic para abrir el selector de archivos.

**Anatomía (estado inicial):**
```
[ícono de upload — 40×40px — rgba(255,255,255,0.40)]
[texto primario — 17px, 500]
[texto hint — 13.5px, --sub]
[link tutorial — 13px, 500, --accent]
[input type="file" — invisible, cubre toda la zona]
```

**Medidas:**
- Contenedor `.drop-area`: padding 32px.
- Zona `.dz`: height 272px, border-radius 10px.
- Ícono margin-bottom: 18px.
- Texto primario margin-bottom: 9px.
- Texto hint margin-bottom: 22px.
- Borde: SVG dashed inline (stroke-opacity 0.1, stroke-dasharray 3 4.5).
- Textura interior: puntos SVG inline (24px tile, fill-opacity 0.02).

**Comportamiento:**
- Hover en zona: `background-color: rgba(255,255,255,0.013)`.
- Hover en ícono: `transform: translateY(-4px)` (transición 0.22s cubic-bezier(0.2,0,0,1)).
- Drag over: fondo verde `rgba(0,200,150,0.06)` + outline `1.5px solid rgba(0,200,150,0.4)`.
- Error: fondo rojo `rgba(226,75,74,0.05)` + outline rojo. Se revierte automáticamente a los 4 segundos.
- El `input[type="file"]` tiene `position: absolute; inset: 0; opacity: 0`. Cubre toda la zona, no solo el texto.

**Copy estándar:**
- Primario: "Arrastra aquí tu CSV de [Exchange]"
- Hint: descripción del contenido esperado del CSV (sin jerga técnica del exchange)
- Tutorial: "▶ Ver vídeo para descargar el CSV (2 min)"

---

### 6.4 Separator

**Finalidad:** Separador visual entre bloques internos del panel.

```css
.sep { height: 1px; background: rgba(255,255,255,0.065); }
```

Aparece entre Drop Area y Config, y entre Config y Benefits.

---

### 6.5 Name Input

**Finalidad:** Campo de texto para el nombre del usuario, que aparecerá en el informe PDF.

**Medidas:**
- width: 250px (colapsa a 100% en mobile).
- padding: 11px 14px.
- border-radius: `--r-sm` (8px).
- font-size: 14px, DM Sans, color `--text`.
- border: 1px solid rgba(255,255,255,0.1).
- background: rgba(255,255,255,0.04).

**Estados:**
- Hover: border-color → rgba(255,255,255,0.18).
- Focus: border-color → rgba(0,200,150,0.4); background → rgba(255,255,255,0.055).
- Placeholder: color `--dim`, opacity 0.9.

---

### 6.6 Year Chip

**Finalidad:** Selector del ejercicio fiscal. Permite seleccionar uno, varios, o todos los años detectados en el CSV.

**Anatomía:** Botón tipo pill. Siempre hay un chip "Todos" primero, seguido de los años detectados.

**Medidas:**
```css
height: 34px;
padding: 0 15px;
border-radius: 999px;
border: 1px solid rgba(255,255,255,0.1);
font-size: 13px; font-weight: 500;
```

**Estados:**

| Estado | Background | Color | Border |
|---|---|---|---|
| Normal | transparent | `--muted` | rgba(255,255,255,0.1) |
| Hover | — | `--text` | rgba(255,255,255,0.22) |
| Active (año) | `--accent-dim` | `--accent` | `--accent` |
| Active ("Todos") | `--accent` | #0a0a0a | `--accent` |
| Focus visible | — | — | outline 2px rgba(0,200,150,0.5) offset 2px |

**Comportamiento:** Los chips de año se detectan automáticamente del CSV. El año más reciente se selecciona por defecto. El chip "Todos" marca todos los años como seleccionados.

---

### 6.7 CTA Principal

**Finalidad:** Disparar el análisis. Es el único botón de acción primaria visible en la página.

**Medidas:**
```css
height: 42px;
padding: 0 26px;
border-radius: var(--r-sm); /* 8px */
font-family: var(--font-display); /* Syne */
font-weight: 700;
font-size: 15px;
letter-spacing: 0.01em;
```

**Copy estándar:** "Generar informe →"

**Estado deshabilitado:** el atributo `disabled` controla totalmente el estilo. Background gris muy tenue, texto casi invisible, `cursor: not-allowed`.

**Estado habilitado:** gradiente verde + glow animado. Hover eleva el botón `translateY(-1px)`. Active aplica `scale(0.985)`.

**Regla:** El CTA solo se habilita cuando hay un archivo seleccionado Y al menos un ejercicio seleccionado (o no hay años detectados).

---

### 6.8 Benefit Card

**Finalidad:** Reforzar la confianza del usuario con cuatro razones concretas de valor, dentro del panel.

**Anatomía:**
```
[ícono SVG 15×15 — --accent, opacity 0.85] [título 12.5px 600 --sub]
                                            [descripción 11.5px #a8a49d]
```

**Medidas:**
- padding: 16px 20px.
- gap entre ícono y texto: 11px.
- Ícono margin-top: 2px (alineación visual con el texto).
- margin-bottom del título: 3px.

**Grid:** 4 columnas, separadas por el fondo del grid visible a través del gap de 1px.

**Regla:** Siempre cuatro benefits. Los iconos son SVG inline, `stroke="currentColor"`, 15×15px.

---

### 6.9 Done State

**Finalidad:** Estado de éxito del panel después de generar el informe. Reemplaza completamente el contenido del panel.

**Anatomía:**
```
[ícono SVG check 36×36px — --accent]
[título — Syne 700 20px]
[subtítulo — DM Sans 14px --muted]
[botón "Nuevo análisis"] [link "Analizar otro exchange →"]
```

**Medidas:**
- padding: 48px 32px.
- min-height: 220px.
- Done button: height 40px, padding 0 22px, border-radius `--r-sm`, DM Sans 500 14px.
- Done button background: rgba(255,255,255,0.05), borde `--border-hi`.
- Done link: font-size 13px, color `--muted`.

**Activación:** `.work-zone.done` → Drop Area, separadores, Config, Benefits: `display: none`. `.done-state`: `display: flex`.

---

### 6.10 Progress Bar

**Finalidad:** Feedback de procesamiento mientras el servidor analiza el CSV.

```css
.progress-track { height: 4px; background: var(--surface2); border-radius: 100px; }
.progress-fill  { background: var(--accent); transition: width 0.7s ease; }
```

Acompañada de mensajes de estado en `--muted` y porcentaje en `--accent`, usando `--font-mono`.

Mensajes estándar: "Leyendo CSV…" → "Clasificando operaciones…" → "Aplicando FIFO…" → "Calculando resultados…" → "Generando informe…"

---

### 6.11 Empty State

**Finalidad:** Estado inicial de la sección de resultados, antes de cualquier análisis.

```css
border: 1px solid var(--border);
border-radius: 16px;
padding: 4rem 2rem;
text-align: center;
```

Contiene: emoji decorativo (2.5rem, opacity 0.5) + H3 (Syne, 1.2rem) + párrafo descriptivo (0.9rem, `--muted`).

---

### 6.12 Error State

**Finalidad:** Mostrar errores del análisis de forma accionable. Nunca mostrar mensajes técnicos crudos.

**Anatomía:**
```
[ícono emoji] [título del error en --red]
[descripción del error con instrucciones]
[lista numerada de pasos si aplica]
[botón "← Volver a intentarlo"]
```

Cada tipo de error tiene su propio ícono y título. Los errores de formato incorrecto incluyen instrucciones paso a paso de cómo obtener el archivo correcto.

---

### 6.13 KPI Card

**Finalidad:** Mostrar los cuatro indicadores principales del análisis en una vista de un vistazo.

**Grid:** `repeat(4, 1fr)`, gap 1px, border-radius 12px.

```css
.kpi-card  { background: var(--surface); padding: 1.25rem 1rem; text-align: center; }
.kpi-label { font-size: 10px; font-weight: 500; text-transform: uppercase; letter-spacing: 0.1em; color: --muted; }
.kpi-value { font-family: --font-display; font-size: clamp(1rem, 2.2vw, 1.4rem); font-weight: 800; }
```

Los cuatro KPIs estándar: Operaciones / Ganancias brutas (verde) / Pérdidas brutas (rojo) / Resultado neto (verde o rojo según signo).

---

### 6.14 Badge de tipo de operación

**Finalidad:** Identificar visualmente el tipo de operación en la tabla.

```css
.badge       { display: inline-flex; align-items: center; gap: 4px; font-size: 10px; padding: 2px 7px; border-radius: 100px; font-weight: 500; text-transform: uppercase; }
.badge-swap  { background: rgba(0,200,150,0.1);  color: var(--accent); }
.badge-venta { background: rgba(226,75,74,0.1);  color: var(--red); }
```

---

## 7. Estados

La interfaz tiene exactamente estos estados, mutuamente excluyentes dentro de su alcance:

### Panel (Work Zone)

| Estado | Qué se muestra | Qué desaparece | Cómo se activa |
|---|---|---|---|
| **Inicial** | Drop Area + Separadores + Config + Benefits | Done State | Al cargar la página o tras reset |
| **Archivo seleccionado** | Panel-meta con nombre del archivo visible | — | Al soltar o seleccionar un archivo válido |
| **Drag over** | Drop Zone con borde y fondo verde | — | Al arrastrar un archivo sobre la zona |
| **Error de archivo** | Drop Zone en modo error (borde rojo, texto rojo) | — | Archivo inválido (no CSV, >10MB, vacío) |
| **Procesando** | Botón CTA con texto "Procesando…" deshabilitado | — | Al pulsar el CTA |
| **Completado (done)** | Done State (check + título + botones) | Drop Area, Config, Benefits | Respuesta OK del servidor |

### Resultados (debajo del panel)

| Estado | Qué se muestra |
|---|---|
| **empty** | Empty State (estado vacío inicial) |
| **loading** | Loading State (barra de progreso) |
| **error** | Error State (error descriptivo + retry) |
| **results** | Results Content (KPI grid + tabs + tablas) |

Solo uno de estos estados es visible en cada momento. La función `showState(state)` controla la visibilidad mediante `display`.

### Post-análisis

Tras el análisis exitoso, aparecen simultáneamente:
1. Done State dentro del panel.
2. `instruccionesPost` debajo del panel.
3. `btnDownload` en el header de resultados.
4. Results Content con los datos.

El usuario puede volver al estado inicial pulsando "Nuevo análisis" (Done State) o el botón del panel-meta.

---

## 8. Responsive

### Breakpoints

| Breakpoint | Contexto |
|---|---|
| > 960px | Desktop amplio |
| 768px – 960px | Desktop compacto / Tablet landscape |
| 540px – 768px | Tablet portrait / Mobile grande |
| 380px – 540px | Mobile estándar |
| < 380px | Mobile pequeño |

### Reglas por breakpoint

#### ≤ 960px

```css
.page-title { font-size: 52px; }
.hero-sub   { font-size: 15px; }
```

#### ≤ 768px

```css
:root { --radius: 12px; --r-in: 8px; }

.page, .results-wrap { padding-left: 16px; padding-right: 16px; }
.hero       { padding: 48px 0 28px; }
.page-title { font-size: 42px; letter-spacing: -0.03em; }
.trust-row  { gap: 14px; }
.drop-area  { padding: 24px; }
.dz         { height: 240px; }
.config     { padding: 18px 24px; flex-wrap: wrap; gap: 12px; }
.f-name     { width: 100%; }
.benefits   { grid-template-columns: repeat(2, 1fr); }
.kpi-grid   { grid-template-columns: repeat(2, 1fr); }
.results-header-row { flex-direction: column; align-items: flex-start; }
.btn-download-hero  { width: 100%; justify-content: center; }
```

#### ≤ 540px

```css
.hero       { padding: 38px 0 22px; }
.page-title { font-size: 36px; letter-spacing: -0.028em; line-height: 1.06; }
.hero-sub   { font-size: 14px; line-height: 1.6; }
.trust-row  { flex-direction: column; align-items: flex-start; gap: 9px; margin-top: 16px; }
.tb-text    { white-space: normal; font-size: 12px; }
.pre-note   { margin-top: 22px; font-size: 12px; }
.drop-area  { padding: 18px; }
.dz         { height: auto; min-height: 212px; padding: 24px 16px; }
.dz-primary { font-size: 15px; }
.dz-hint    { font-size: 13px; margin-bottom: 18px; }
.config     { padding: 16px 18px; flex-direction: column; }
.f-name, .f-year { width: 100%; }
.cta        { width: 100%; height: 44px; }
.benefits   { grid-template-columns: repeat(2, 1fr); }
```

#### ≤ 380px

```css
.page-title { font-size: 30px; }
.hero-sub   { font-size: 13.5px; }
.dz-primary { font-size: 14px; }
.benefits   { grid-template-columns: 1fr; }
```

### Comportamiento del Trust Row en mobile

En ≤ 540px, el Trust Row cambia de `flex-row` con `flex-wrap` a `flex-direction: column`, con todos los ítems alineados a la izquierda. El texto deja de tener `white-space: nowrap`.

### Comportamiento del Footer en mobile

En ≤ 600px: `.footer-inner { flex-direction: column; align-items: flex-start; gap: 10px; }`.

---

## 9. Accesibilidad

### Contraste

Los pares de color usados en el sistema:

| Texto | Fondo | Ratio aproximado | Nivel |
|---|---|---|---|
| `--text` #F2EFE9 | `--bg` #080c17 | > 15:1 | AAA |
| `--sub` #BFBBB3 | `--bg` #080c17 | > 8:1 | AAA |
| `--muted` #969189 | `--bg` #080c17 | ≈ 4.5:1 | AA |
| `--accent` #00C896 | `--bg` #080c17 | > 5:1 | AA |
| #03110a (CTA text) | #00D8A7 (CTA bg) | > 8:1 | AAA |
| `--red` #e24b4a | `--bg` #080c17 | > 4.5:1 | AA |

No se usa `--dim` (#67645E) para texto con información relevante — solo para placeholders.

### Navegación con teclado

- Todos los elementos interactivos son nativamente enfocables: `<button>`, `<input>`, `<a>`.
- El `input[type="file"]` invisible dentro del Drop Zone se activa con Enter/Space al enfocar la zona.
- Los Year Chips tienen `focus-visible` explícito: `outline: 2px solid rgba(0,200,150,0.5); outline-offset: 2px`.
- El CTA tiene `focus-visible`: `outline: 2px solid rgba(0,200,150,0.7); outline-offset: 3px`.
- Las pills de año en resultados usan `<button>` nativos.

### Áreas clicables

- Drop Zone: toda la zona de 272px de alto es clicable (el input invisible cubre `inset: 0`).
- Year Chips: mínimo 34px de alto.
- CTA: 42px de alto (44px en mobile pequeño).
- Done buttons: 40px de alto.
- Trust Items: no son clicables — son informativos.

### Tamaños mínimos

El tamaño mínimo de área clicable en mobile es 40px de alto. Se respeta en todos los elementos interactivos.

### Reset y comportamiento del scroll

```css
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; max-width: 100%; }
html { scroll-behavior: smooth; }
```

El `max-width: 100%` en el reset previene desbordamientos horizontales en mobile.

---

## 10. Reglas de consistencia

Estas reglas no pueden romperse en ninguna herramienta nueva del silo:

**Grid y composición:**
- El Hero y el panel comparten siempre el mismo `max-width` (`--w: 1060px`). Nunca un Hero más estrecho o más ancho que el panel.
- Los `<br>` del H1 son intencionales y parte del diseño. No se eliminan por comodidad.

**CTAs y acciones:**
- No existen dos CTAs principales simultáneamente visibles.
- El CTA solo se habilita cuando el usuario puede efectivamente usarlo (archivo + ejercicio seleccionados).
- El botón de descarga del PDF nunca es el CTA principal — es un elemento secundario en el área de resultados.

**Flujo de confianza:**
- Los mensajes de confianza (Trust Row) siempre aparecen antes del área de subida.
- La Pre-note siempre aparece entre el Trust Row y el panel.
- El usuario siempre debe saber cuál es la siguiente acción: si no hay archivo, el CTA está deshabilitado; si hay un error, hay un botón de retry; si el análisis terminó, hay un botón de descarga y uno de nuevo análisis.

**Estado final:**
- Tras generar el informe, nunca puede quedar un estado ambiguo. El panel debe transformarse visiblemente al Done State, y los resultados deben ser visibles debajo.
- El estado de "trabajo completado" siempre ofrece dos salidas: nuevo análisis en la misma herramienta, o ir a analizar otro exchange.

**Terminología:**
- Nunca usar nomenclatura interna del exchange para describir el CSV.
- El tutorial link siempre tiene el patrón: "▶ Ver vídeo para descargar el CSV (duración)".
- Los errores siempre son accionables: explican qué pasó y qué tiene que hacer el usuario.

**Estructura del panel:**
- El orden de bloques dentro del panel es invariable: Drop Area → Separator → Config → Separator → Benefits.
- Los Benefits están siempre dentro del panel, nunca fuera.
- Nunca añadir un bloque "Cómo funciona en 3 pasos" ni una sección FAQ en la página de herramienta.

**Arquitectura:**
- La lógica de negocio nunca se mezcla con la capa visual.
- La constante `EXCHANGE_PAGE` al inicio del script identifica el exchange activo.

---

## 11. Anti-patrones

Errores documentados que no deben repetirse en ninguna herramienta del silo. Algunos proceden directamente del desarrollo de Binance; otros son consecuencias previsibles de no seguir el sistema.

---

**Hero más estrecho que el panel.**
La composición se rompe visualmente: el encabezado parece desconectado del área de trabajo, como si fueran dos piezas de páginas distintas. El ancho del Hero no es una variable de diseño — es el mismo que el del panel, siempre.

---

**Dos CTAs principales visibles simultáneamente.**
Obliga al usuario a tomar una decisión que debería haber tomado el producto. Si coexisten "Generar informe" y "Descargar PDF" como acciones de igual peso, el usuario no sabe qué se supone que debe hacer. Uno de los dos es siempre secundario.

---

**Vídeo incrustado antes del formulario.**
Un reproductor de vídeo (iframe de YouTube) antes del Drop Zone compite visualmente con el CTA, ocupa espacio que el usuario que ya sabe qué hacer tiene que desplazar, y ralentiza la percepción de velocidad de la herramienta. La solución aprobada: un enlace de texto dentro del Drop Zone, disponible para quien lo necesite, invisible para quien no lo necesita.

---

**Formulario sin estado final.**
Un flujo que permite subir un archivo y pulsar un botón pero no transforma la interfaz tras el análisis deja al usuario en un estado ambiguo: ¿terminó? ¿falló? ¿tengo que hacer algo más? El Done State no es decorativo — es la confirmación explícita de que el trabajo terminó.

---

**Duplicar información entre bloques.**
El mismo mensaje no puede aparecer en el Hero, en los Benefits y en las instrucciones post-análisis. Cada bloque tiene una función asignada. Si la misma idea aparece en dos sitios, uno de ellos está mal ubicado o uno de los dos está de más.

---

**Diseñar cada exchange desde cero.**
El coste de rediseñar es siempre mayor que el de adaptar. Cada decisión tomada en Binance existe precisamente para no tener que volverse a tomar. Una herramienta nueva que empieza desde una pantalla en blanco acumula deuda de diseño y fragmenta la coherencia del silo.

---

**Componentes con anchos distintos entre herramientas.**
Si el panel de Kraken tiene un `max-width` diferente al de Binance, el silo se fragmenta visualmente. Un usuario que navega entre herramientas lo detecta inmediatamente aunque no sepa nombrarlo.

---

**Estados ambiguos.**
Una interfaz que no comunica si está cargando, si terminó, o si falló, genera ansiedad. Cada estado de la herramienta — inicial, procesando, éxito, error — tiene una representación visual inequívoca. No existe un estado intermedio sin representación.

---

**Usar nomenclatura interna del exchange en la interfaz.**
"Transaction History", "Historial de Operaciones Spot", "Spot Order History" son nombres internos que cambian entre versiones del exchange y confunden al usuario no técnico. La interfaz dice "CSV de Binance". El usuario que exportó el archivo ya sabe qué archivo tiene.

---

**Sección "Cómo funciona en 3 pasos" dentro de la herramienta.**
Una sección explicativa dentro de la herramienta es un síntoma de que la interfaz no es suficientemente clara por sí misma. La herramienta debe ser autoexplicativa. Si no lo es, la solución es mejorar la interfaz, no añadir una sección de instrucciones sobre ella. Las explicaciones extensas pertenecen a `/como-funciona` o a `/faq`.

---

**Benefits fuera del panel.**
Los cards de beneficio colocados bajo el panel como una fila independiente parecen marketing de landing page, no parte de la herramienta. Dentro del panel, integrados bajo el Config Row, son parte de la experiencia. Fuera, son decoración que compite con el flujo.

---

**Referencias a datos del usuario que no aportan nada a la tarea.**
Texto como "Último análisis: 14 jun 2025" o "Has analizado 3 ejercicios" aumenta la carga cognitiva sin facilitar la tarea actual. La herramienta resuelve una tarea específica; no es un dashboard de historial. Cualquier información que no ayude al usuario a completar el análisis actual es ruido.

---

**Mensajes de error técnicos sin traducción.**
Un error como "column 'Realized Profit' not found at line 3" no le dice al usuario qué tiene que hacer. Los errores tienen que ser accionables: identificar qué pasó, por qué, y cuáles son los pasos exactos para resolverlo. Un mensaje técnico que llega hasta la interfaz es un bug de UX, no solo un bug de formato.

---

**FAQ dentro de la herramienta.**
Una sección de preguntas frecuentes dentro de la página de la herramienta fragmenta el foco del usuario y compite con el flujo principal. Si una pregunta es suficientemente frecuente para documentarla, pertenece a `/faq`, con su propia URL y estructura.

---

## 12. Decisiones de diseño

Este capítulo documenta el razonamiento de producto detrás de las decisiones clave. El objetivo es que dentro de uno, dos o cinco años — cuando alguien tenga que tomar una decisión que afecte a una de estas áreas — pueda entender no solo qué decidimos, sino por qué.

---

### Hero y panel con el mismo ancho

En las primeras iteraciones, el Hero tenía un `max-width` menor que el panel. La hipótesis era que un encabezado más estrecho crearía un efecto de "embudo" hacia el área de trabajo. El resultado fue el contrario: el panel se veía demasiado ancho, el Hero demasiado ajustado, y la composición transmitía descuido en lugar de jerarquía.

La decisión de igualar los anchos resuelve el problema de raíz: la página tiene una sola columna de peso consistente. El usuario no percibe que el encabezado y el formulario sean piezas distintas — percibe una sola herramienta.

---

### El vídeo dejó de estar incrustado

En versiones anteriores existía un reproductor de YouTube incrustado antes del Drop Zone, para enseñar al usuario cómo descargar el CSV desde Binance. El problema tiene tres capas:

Primero, el vídeo compite visualmente con el CTA: el usuario no sabe si tiene que ver el vídeo antes de subir el archivo, o si puede saltárselo.

Segundo, el usuario que ya sabe qué hacer — que es la mayoría tras la primera visita — tiene que desplazar el vídeo para llegar al formulario. La herramienta penaliza al usuario recurrente para servir al usuario que llega por primera vez.

Tercero, el iframe de YouTube ralentiza la carga de la página y añade dependencia de un servicio externo en el camino crítico de la interfaz.

La solución: un enlace de texto dentro del Drop Zone ("▶ Ver vídeo para descargar el CSV (2 min)") que abre el vídeo en una nueva pestaña. El usuario que lo necesita lo tiene a un clic. El que no lo necesita no lo ve.

---

### Por qué no existe un selector de exchange dentro de la herramienta

En una iteración se exploró añadir un selector de exchange al formulario ("¿Para qué exchange es este CSV?"), con la idea de que una sola URL pudiera servir para todos los exchanges. El problema es que añade una decisión al flujo del usuario que no debería existir.

El usuario que llega a `/binance` ya tomó esa decisión: tiene un CSV de Binance y quiere declarar Binance. El selector es ruido — una pregunta cuya respuesta ya está implícita en la URL. Además, un selector único requiere que el frontend conozca todos los parsers, lo que mezcla la lógica de negocio con la interfaz.

La arquitectura correcta es una URL por exchange. La decisión ya está tomada antes de cargar la página.

---

### Por qué el Hero es tan corto

El Hero de cada herramienta tiene tres elementos: H1, subtítulo (una frase), y Trust Row (cuatro ítems en una línea). No hay más.

La razón no es minimalismo estético — es que el Hero es un umbral, no una sala. El usuario llega con una tarea. Necesita confirmar en segundos que está en el sitio correcto y empezar. Cada elemento adicional en el Hero es un elemento que retrasa esa confirmación.

El Hero responde a una sola pregunta: "¿Es esto para mí?". Si la respuesta es sí, el usuario se desplaza al panel. Si la respuesta es no, el usuario abandona. Nada de lo que pueda añadirse al Hero cambia ese resultado.

---

### Por qué existe el estado "Trabajo completado"

Sin el Done State, tras el análisis exitoso el panel queda en su estado inicial — Drop Zone vacío, chips de año, CTA deshabilitado — exactamente como al principio. El informe está en la sección de resultados, debajo, pero nada en el panel indica que el proceso terminó.

El Done State resuelve la ambigüedad: el panel cambia visiblemente. Un ícono de check, el texto "Tu informe fiscal ya está listo", y dos acciones claras. El usuario no tiene que buscar nada — el panel le dice exactamente qué pasó y qué puede hacer a continuación.

También tiene un efecto secundario útil: el Done State obliga al panel a estar limpio cuando el usuario quiere hacer un nuevo análisis. Al pulsar "Nuevo análisis", todo vuelve al estado inicial. No hay archivos residuales, no hay chips de año seleccionados, no hay confusión sobre si el análisis anterior ya terminó.

---

### Por qué la interfaz prioriza claridad frente a cantidad de información

El primer impulso cuando se diseña una herramienta fiscal es mostrar todo lo que el sistema conoce: el historial completo, todos los activos, todas las operaciones de todos los años, todos los avisos. La hipótesis implícita es que más información reduce la incertidumbre del usuario.

En la práctica, ocurre lo contrario. Una pantalla densa con mucha información fiscal — especialmente para un usuario que no es experto en fiscalidad de criptomonedas — aumenta la ansiedad en lugar de reducirla. El usuario no sabe qué mirar primero, ni qué es relevante para su declaración.

La herramienta muestra exactamente lo que el usuario necesita para declarar correctamente: cuatro KPIs, una tabla de operaciones, un PDF. El análisis detallado existe (desglose por activo, posición actual, rendimientos) pero no es el objetivo principal — está disponible para quien quiera profundizar, en tabs, sin interrumpir el flujo del usuario que solo necesita el PDF.

---

### Por qué los Benefits están dentro del panel

La alternativa natural es colocar los cards de beneficio como una sección independiente bajo el panel, a modo de "por qué usar esta herramienta". El problema es que fuera del panel se perciben como marketing, no como parte de la herramienta.

Dentro del panel, integrados como el bloque final, son parte del producto. Visualmente forman parte del mismo contenedor que el Drop Zone y el formulario. Funcionalmente, desaparecen cuando ya no son necesarios: en el Done State, el panel muestra el estado de éxito sin competencia visual de los benefits.

---

### Por qué el Drop Zone usa un borde SVG en lugar de CSS

Un `border: 1.5px dashed` con `border-radius` no renderiza de forma consistente entre navegadores: el patrón de guiones no se adapta correctamente al radio de las esquinas. El resultado son esquinas con el dash mal distribuido.

El SVG inline como `background-image` resuelve el problema: el borde es un elemento vectorial cuyo `stroke-dasharray` es exacto y cuyo `rx/ry` está controlado. El resultado es visualmente idéntico en Chrome, Safari y Firefox.

---

### Por qué los chips de año preseleccionan el año más reciente

La mayoría de los usuarios que usan la herramienta están declarando el ejercicio anterior — el año más reciente en su CSV. Preseleccionar el año más reciente ahorra una interacción en el 80% de los casos, sin impedir que el usuario cambie la selección cuando necesita declarar un año anterior o todos los ejercicios.

El chip "Todos" está disponible siempre, como primera opción en la lista. El usuario que necesita todos los años lo tiene a un clic.

---

### Por qué los errores tienen mensajes distintos según el tipo

Un error genérico "El fichero no es válido" no le dice al usuario qué tiene que hacer. Los errores están categorizados por tipo: CSV incorrecto (con instrucciones exactas de cómo obtener el correcto), fichero demasiado grande, fichero vacío, error de conexión, límite de análisis alcanzado.

Cada categoría tiene su propio ícono, título y descripción. En los casos de CSV incorrecto — el error más frecuente y el que más confunde al usuario — la descripción incluye los pasos exactos para obtener el archivo correcto desde el exchange.

El objetivo no es informar del error técnico. Es decirle al usuario exactamente qué tiene que hacer para resolverlo, sin que tenga que salir de la página ni consultar documentación externa.

---

## 13. Adaptación a otros exchanges

### Elementos que cambian por exchange

Estos son los únicos elementos que varían entre herramientas:

| Elemento | Dónde | Qué cambia |
|---|---|---|
| `<title>` y `<meta description>` | `<head>` | Nombre del exchange y copy SEO |
| H1 | `.page-title` | Línea 2 ("fiscal de [Exchange]") y distribución con `<br>` |
| Exchange en `h-accent` | `<span class="h-accent">` | Nombre del exchange |
| Subtítulo del Hero | `.hero-sub` | Copy específico del exchange y tipo de informe |
| Trust Items | `.tb-text` | Copy adaptado (compatibilidad con el CSV del exchange) |
| Hint del Drop Zone | `#dropHint` | "Arrastra aquí tu CSV de [Exchange]" |
| Hint secundario | `.dz-hint` | Descripción del contenido del CSV |
| Tutorial link | `#dzTutorial` | URL del vídeo tutorial del exchange específico |
| Benefit cards | `.benefit` | Textos específicos del exchange y su método |
| `EXCHANGE_PAGE` | JS | Identificador del exchange para la API |
| Parser del CSV | Backend | `clasificador_[exchange].py` |
| Campo `exchange` en FormData | JS | `formData.append('exchange', '[exchange]')` |
| Nombre del PDF descargado | JS | `download="informe_fiscal_[exchange].pdf"` |
| Instrucciones post-análisis | `#instruccionesPost` | Casillas IRPF y pasos específicos del exchange |
| Mensajes de error | JS | Textos adaptados a los errores del CSV del exchange |

### Elementos que nunca cambian

Estos elementos son invariables en cualquier herramienta:

- Tokens CSS (colores, tipografía, radii, `--w`).
- Estructura del panel (Drop Area → Separator → Config → Separator → Benefits).
- Arquitectura de la página (orden de bloques).
- Sistema de grid y breakpoints responsive.
- Comportamiento de los estados (drag, error, loading, done).
- Lógica del selector de año (chips, detección desde CSV, selección por defecto).
- Función de validación del archivo (tipo, tamaño, contenido vacío).
- CTA y sus estados (disabled/enabled, glow, hover).
- Done State y su estructura.
- Footer y navegación.
- Motor FIFO y lógica de cálculo fiscal.

### Proceso de incorporación de un nuevo exchange

1. Duplicar `binance_v2.html` con el nuevo nombre (`kraken_v1.html`, etc.).
2. Modificar únicamente los elementos de la tabla anterior.
3. Crear el clasificador de backend (`clasificador_kraken.py`) siguiendo el patrón existente.
4. Validar con el checklist de §14 antes de publicar.

---

## 14. Checklist de validación

Antes de aprobar cualquier nueva herramienta del silo, verificar cada punto:

### Consistencia visual

- [ ] Los tokens CSS son exactamente los definidos en §5. No hay colores hardcoded fuera de los tokens.
- [ ] Las familias tipográficas son Syne y DM Sans. No hay otras fuentes.
- [ ] Los radii son `--radius` (14px), `--r-in` (10px), `--r-sm` (8px). Ninguno diferente.
- [ ] El `max-width` del contenedor y del Hero coincide con `--w` (1060px).
- [ ] El panel tiene el gradiente de fondo, borde `--border-hi`, y las cuatro capas de sombra.

### Responsive

- [ ] El layout es correcto en 1200px, 960px, 768px, 540px y 375px.
- [ ] El Trust Row colapsa a columna en ≤ 540px.
- [ ] El Drop Zone en mobile tiene `height: auto; min-height: 212px`.
- [ ] El CTA en mobile pequeño ocupa `width: 100%`.
- [ ] Los Benefits pasan a 2 columnas en ≤ 768px y a 1 columna en ≤ 380px.
- [ ] No hay desbordamiento horizontal en ningún breakpoint.

### Accesibilidad

- [ ] Todos los elementos interactivos son navegables con teclado.
- [ ] Los Year Chips tienen `focus-visible` con outline verde.
- [ ] El CTA tiene `focus-visible` con outline verde.
- [ ] El contraste de todos los pares texto/fondo es ≥ 4.5:1 (AA).
- [ ] El Drop Zone completo es clicable (el input cubre `inset: 0`).
- [ ] Los botones tienen al menos 40px de alto en mobile.

### Estados

- [ ] Estado inicial: Drop Zone visible, CTA deshabilitado, resultados en estado `empty`.
- [ ] Drag over: fondo verde + outline verde en Drop Zone.
- [ ] Archivo inválido: Drop Zone en error-zone durante 4 segundos, luego reset.
- [ ] Archivo válido: nombre del archivo visible en panel-meta, chips de año detectados, CTA habilitado.
- [ ] Procesando: CTA deshabilitado con texto "Procesando…", loading state visible.
- [ ] Done state: panel transformado, instrucciones post visibles, botón de descarga visible.
- [ ] Error de API: error state visible con mensaje descriptivo y botón de retry.
- [ ] Reset: todos los estados vuelven al inicial correctamente.

### Funcionamiento

- [ ] El archivo es validado antes de enviarse (tipo .csv, tamaño ≤ 10MB, no vacío).
- [ ] Los años se detectan del CSV y se renderizan como chips.
- [ ] El año más reciente se selecciona por defecto.
- [ ] El valor del campo `exchange` en FormData coincide con el clasificador de backend.
- [ ] El PDF descargado tiene el nombre correcto (`informe_fiscal_[exchange].pdf`).
- [ ] El enlace de descarga apunta a `/api/descargar/{token}?exchange=[exchange]`.
- [ ] El tutorial link abre en nueva pestaña con `noopener`.
- [ ] El guard de autenticación redirige a `/login/` si no hay sesión activa.

### Auditoría UX

- [ ] El usuario puede completar el flujo completo (subir → generar → descargar) sin instrucciones externas.
- [ ] En ningún momento hay dos CTAs principales visibles simultáneamente.
- [ ] Los Trust Items aparecen antes del Drop Zone.
- [ ] La Pre-note está presente entre el Hero y el panel.
- [ ] El copy del Drop Zone no usa nomenclatura interna del exchange.
- [ ] Los errores son accionables (explican qué hacer, no solo qué falló).
- [ ] El Done State ofrece dos salidas claras.

### Coherencia con el Design System

- [ ] La estructura del panel es: Drop Area → Separator → Config → Separator → Benefits. Sin excepciones.
- [ ] No existe ninguna sección "Cómo funciona" o FAQ en la página.
- [ ] Los Benefits están dentro del panel, no fuera.
- [ ] La constante `EXCHANGE_PAGE` está definida al inicio del script.
- [ ] El `<br>` del H1 produce la distribución tipográfica correcta en todos los breakpoints.
- [ ] Ningún anti-patrón del §11 está presente.

---

## 15. Evolución del Design System

### Estado actual

Este documento describe la versión 1 del Exchange Tool Design System. La implementación de referencia es `/fiscal_app_export/templates/binance_v2.html`. Todo lo que está aquí documentado fue destilado a partir del desarrollo, iteración y aprobación de esa herramienta.

Binance es la herramienta de referencia por ser la primera: todas las decisiones de diseño se tomaron ahí, todas las iteraciones ocurrieron ahí, y todos los anti-patrones documentados en §11 fueron errores cometidos y corregidos en ese proceso. Cualquier duda sobre la implementación correcta de un componente tiene su respuesta en `binance_v2.html`.

### Objetivo del silo

El objetivo a medio plazo es que las siguientes herramientas — Kraken, Coinbase, Bitget, Nexo, Crypto.com, Bit2Me, y cualquier otro exchange que se incorpore — reutilicen este sistema sin tomar ninguna decisión de diseño que no esté ya resuelta aquí.

Un desarrollador que incorpore Kraken no debería tomar ninguna decisión sobre colores, tipografía, espaciados, estructura del panel, comportamiento de los estados, o responsive. Solo debería adaptar los elementos listados en §13 y validar con el checklist de §14.

El ahorro no es solo de tiempo — es de coherencia. Un silo de herramientas donde cada una tomó sus propias decisiones de diseño es un silo fragmentado. Un silo donde todas las herramientas comparten el mismo sistema visual es un producto.

### Cómo evoluciona este documento

Este documento evoluciona cuando cambia el sistema, no cuando cambia una implementación.

- Si se añade un nuevo componente aprobado → se documenta en §6.
- Si se descubre un nuevo anti-patrón → se añade en §11.
- Si se toma una decisión de diseño con razonamiento de producto → se documenta en §12.
- Si una regla de §10 se modifica → se actualiza §10 y se revisa §14.

Lo que no justifica una actualización de este documento: cambios de copy específico de un exchange, correcciones de bugs del backend, ajustes visuales menores que no afectan al sistema.

### Versiones

**v1 — 2026-06-28**
Primera versión del sistema. Destilada a partir de la implementación de Binance. Cubre filosofía, arquitectura, tokens, componentes, estados, responsive, accesibilidad, reglas, anti-patrones, decisiones, adaptación y checklist.

Cuando el sistema evolucione significativamente — por ejemplo, tras incorporar tres o cuatro exchanges y haber identificado nuevos patrones o revisado decisiones anteriores — se actualizará a v2. El historial de versiones queda registrado en esta sección.

### Criterio para una nueva versión mayor

Una versión mayor (v2, v3) está justificada cuando ocurre alguno de estos eventos:

- Se añade un nuevo tipo de herramienta al silo que requiere un patrón de página diferente.
- Un componente central (Drop Zone, Done State, Trust Row) se rediseña con suficiente impacto visual como para que las herramientas anteriores necesiten actualizarse.
- Los tokens de color o tipografía cambian como decisión de marca.

Los ajustes incrementales — nuevos componentes menores, nuevas reglas, nuevos anti-patrones documentados — no generan una versión mayor.

---

*Este documento es la referencia oficial del Exchange Tool Design System. Cualquier modificación requiere aprobación explícita y debe reflejarse en la implementación de referencia (`binance_v2.html`).*
