---
name: seo-crypto-es
description: >
  Experto SEO especializado en webs de crypto, finanzas personales e impuestos en España y Latinoamérica.
  Usa esta skill siempre que necesites optimizar textos, títulos, meta descriptions, headings, keyword research,
  datos estructurados (schema.org), URLs, alt text, o cualquier elemento SEO de una web relacionada con
  criptomonedas, fiscalidad crypto, exchanges, declaración de impuestos, Hacienda, IRPF, o herramientas
  financieras. También úsala para auditar páginas existentes, sugerir mejoras de contenido orientadas a
  posicionamiento, o estructurar landing pages que conviertan. Si el usuario menciona "SEO", "posicionamiento",
  "Google", "meta tags", "keywords", "schema", "Hacienda", "FIFO", "declaración crypto" o similares en
  contexto de una web, activa esta skill sin esperar a que el usuario lo pida explícitamente.
---

# SEO Crypto ES — Guía de uso

Skill para optimización SEO de webs de crypto y fiscalidad en español, con foco especial en herramientas
orientadas al mercado español (Hacienda, IRPF, Agencia Tributaria) y latinoamericano.

---

## Contexto del proyecto por defecto

**Web**: marianosevilla.com  
**Producto**: Herramienta que genera informes FIFO para la declaración de criptomonedas en Hacienda a partir de CSVs de exchanges.  
**Audiencia principal**: Contribuyentes españoles y latinoamericanos con criptoactivos que deben declarar ganancias/pérdidas patrimoniales.  
**Tono**: Directo, claro, sin tecnicismos innecesarios. Anti-hype. Transmite confianza y credibilidad.  
**Idioma**: Español europeo (España). Usar "declaración de la renta", "Hacienda", "IRPF", "ganancias patrimoniales", nunca anglicismos innecesarios.

---

## Workflows disponibles

### 1. KEYWORD RESEARCH

**Cuándo usarlo**: El usuario quiere saber qué términos posicionar, qué busca su audiencia, o cómo estructurar el contenido.

**Proceso**:
1. Identificar el tema/página objetivo
2. Clasificar keywords por intención:
   - **Informacional**: "cómo declarar crypto en España", "qué es el método FIFO"
   - **Transaccional**: "herramienta informe crypto Hacienda", "calcular plusvalías crypto"
   - **Navegacional**: "marianosevilla.com crypto", "calculadora FIFO criptomonedas"
3. Estimar dificultad y volumen orientativo
4. Priorizar por: intención de compra alta + competencia baja + relevancia exacta

**Keywords semilla para este proyecto** (expandir según página):
- `declarar criptomonedas hacienda`
- `informe FIFO crypto españa`
- `calcular plusvalías criptomonedas`
- `csv exchange hacienda`
- `ganancias patrimoniales bitcoin irpf`
- `modelo 721 criptomonedas`
- `declaración renta crypto 2024`
- Long tails: `cómo rellenar casilla 1626 criptomonedas`, `informe fiscal binance hacienda`

**Output esperado**: Tabla con keyword / intención / prioridad / sugerencia de página donde usarla.

---

### 2. OPTIMIZACIÓN DE TEXTOS (ON-PAGE)

**Cuándo usarlo**: El usuario pasa un texto y quiere mejorarlo para SEO sin perder naturalidad.

**Reglas**:
- Keyword principal en el primer párrafo (primeras 100 palabras)
- Densidad keyword: 1-2% (no forzar, debe sonar natural)
- Usar variantes semánticas y LSI keywords a lo largo del texto
- Párrafos cortos (máx. 3-4 líneas). Frases directas.
- Llamadas a la acción claras orientadas a conversión
- Evitar keyword stuffing. Google penaliza; los usuarios abandonan.

**Output esperado**: Texto reescrito con anotaciones `[SEO: motivo del cambio]` en los puntos clave.

---

### 3. META TAGS

**Cuándo usarlo**: El usuario necesita `<title>` y `<meta description>` para una página.

**Reglas title**:
- Entre 50-60 caracteres (máximo ~580px de ancho en Google)
- Keyword principal al inicio
- Incluir propuesta de valor o diferenciador
- No repetir la keyword exacta más de una vez
- Formato recomendado: `[Keyword principal] — [Beneficio] | [Marca]`

**Reglas meta description**:
- Entre 150-160 caracteres
- Incluir keyword principal y secundaria si cabe
- CTA implícito o explícito ("Genera tu informe en minutos", "Sin conocimientos fiscales")
- No usar comillas dobles (se truncan en SERPs)

**Ejemplo para marianosevilla.com**:
```html
<title>Informe FIFO Crypto para Hacienda — Genera el tuyo en minutos | MarianoSevilla.com</title>
<meta name="description" content="Sube el CSV de tu exchange y obtén el informe FIFO listo para la declaración de criptomonedas en Hacienda. Rápido, preciso y sin conocimientos fiscales.">
```

---

### 4. ESTRUCTURA DE HEADINGS (H1-H6)

**Cuándo usarlo**: El usuario tiene una página o sección y necesita estructurar o revisar los headings.

**Reglas**:
- **H1**: Único por página. Keyword principal. Debe coincidir semánticamente con el `<title>` (no tiene que ser idéntico).
- **H2**: Subtemas principales. Keywords secundarias o variantes.
- **H3**: Detalles de cada subtema. Long tails o preguntas frecuentes.
- **H4-H6**: Usar con moderación, solo si la página es muy extensa.
- Los headings deben contar la historia de la página aunque se lean solos (scan reading).

**Output esperado**: Árbol de headings propuesto con la keyword objetivo de cada uno.

---

### 5. DATOS ESTRUCTURADOS (SCHEMA.ORG)

**Cuándo usarlo**: El usuario quiere rich snippets en Google (estrellitas, FAQs, breadcrumbs, etc.).

**Schemas más relevantes para este proyecto**:

**FAQPage** — para páginas con preguntas frecuentes sobre fiscalidad crypto:
```json
{
  "@context": "https://schema.org",
  "@type": "FAQPage",
  "mainEntity": [{
    "@type": "Question",
    "name": "¿Qué es el método FIFO en criptomonedas?",
    "acceptedAnswer": {
      "@type": "Answer",
      "text": "FIFO (First In, First Out) es el método que Hacienda establece para calcular las ganancias patrimoniales en criptomonedas. Las primeras unidades compradas son las primeras que se consideran vendidas al calcular la plusvalía."
    }
  }]
}
```

**SoftwareApplication** — para la herramienta en sí:
```json
{
  "@context": "https://schema.org",
  "@type": "SoftwareApplication",
  "name": "Generador de Informe FIFO Crypto",
  "applicationCategory": "FinanceApplication",
  "offers": {
    "@type": "Offer",
    "price": "0",
    "priceCurrency": "EUR"
  },
  "operatingSystem": "Web"
}
```

**BreadcrumbList** — para navegación:
```json
{
  "@context": "https://schema.org",
  "@type": "BreadcrumbList",
  "itemListElement": [{
    "@type": "ListItem",
    "position": 1,
    "name": "Inicio",
    "item": "https://marianosevilla.com"
  }]
}
```

---

### 6. AUDITORÍA SEO DE PÁGINA

**Cuándo usarlo**: El usuario pasa el HTML/contenido de una página y quiere un diagnóstico completo.

**Checklist de auditoría**:
- [ ] Title tag presente, longitud correcta, keyword al inicio
- [ ] Meta description presente y optimizada
- [ ] H1 único y con keyword principal
- [ ] Estructura de headings lógica (H1 > H2 > H3)
- [ ] Keyword principal en primeras 100 palabras
- [ ] Imágenes con alt text descriptivo y con keyword donde natural
- [ ] URLs cortas, descriptivas, con guiones (no guiones bajos)
- [ ] Links internos relevantes
- [ ] Schema markup presente
- [ ] Canonical tag correcto
- [ ] Open Graph tags (og:title, og:description, og:image)
- [ ] Velocidad de carga (señalar si hay elementos que la penalizan)
- [ ] Mobile-friendly (señalar problemas evidentes en el código)

**Output esperado**: Lista priorizada de mejoras con impacto estimado (Alto / Medio / Bajo).

---

### 7. OPTIMIZACIÓN DE URLs

**Reglas**:
- Lowercase siempre
- Guiones medios (-) para separar palabras, nunca guiones bajos (_)
- Keyword principal incluida
- Lo más corta posible sin perder descriptividad
- Sin parámetros innecesarios, sin fechas (salvo blog)
- Sin stopwords si no aportan (artículos, preposiciones)

**Ejemplos**:
- ✅ `/informe-fifo-crypto-hacienda`
- ✅ `/como-declarar-criptomonedas`
- ❌ `/pagina?id=123&tipo=herramienta`
- ❌ `/el-mejor-generador-de-informes-fiscales-para-tus-criptomonedas-en-hacienda`

---

### 8. OPEN GRAPH Y TWITTER CARDS

**Cuándo usarlo**: El usuario quiere optimizar cómo se ve su web al compartir en redes sociales.

**Template base**:
```html
<!-- Open Graph -->
<meta property="og:title" content="Informe FIFO Crypto para Hacienda en minutos">
<meta property="og:description" content="Sube el CSV de tu exchange y genera el informe fiscal listo para Hacienda. Sin conocimientos contables.">
<meta property="og:image" content="https://marianosevilla.com/og-image.png">
<meta property="og:url" content="https://marianosevilla.com">
<meta property="og:type" content="website">
<meta property="og:locale" content="es_ES">

<!-- Twitter Card -->
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="Informe FIFO Crypto para Hacienda en minutos">
<meta name="twitter:description" content="Sube el CSV de tu exchange y genera el informe fiscal listo para Hacienda.">
<meta name="twitter:image" content="https://marianosevilla.com/og-image.png">
```

---

## Exchanges soportados — contexto para keywords

La herramienta soporta CSVs de exchanges. Cada exchange es una keyword de long tail con alta intención:
- `informe fiscal binance hacienda`
- `csv kraken declaración renta`
- `coinbase declarar ganancias españa`
- `bybit hacienda informe`
- `kucoin irpf crypto`
- Generar páginas/secciones específicas por exchange si el tráfico lo justifica.

---

## Términos fiscales clave — usar en contenido

Siempre preferir terminología oficial española:
- "ganancias y pérdidas patrimoniales" (no "plusvalías" a secas, aunque se puede usar como sinónimo)
- "Agencia Tributaria" o "Hacienda" (no "fisco")
- "declaración de la renta" o "IRPF" (no "tax return")
- "criptoactivos" (término oficial desde 2023) o "criptomonedas" (más buscado)
- "método FIFO" (obligatorio en España para calcular ganancias en crypto)
- "Modelo 721" (declaración de criptoactivos en el extranjero)
- "casilla 1626 y 1627" (dónde declarar en el modelo 100)

---

## Referencias adicionales

Ver `references/keywords-master.md` para lista expandida de keywords por intención y prioridad.
Ver `references/competidores.md` para análisis de webs competidoras y oportunidades de gap.
