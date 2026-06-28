# EXCHANGE_IMPLEMENTATION_GUIDE.md
### Guía de implementación: cómo construir e integrar un nuevo exchange en el silo

**Versión:** 1.0 — 2026-06-28
**Documento relacionado:** `docs/DESIGN_SYSTEM.md` (estándar visual y de UX)
**Plantilla de referencia:** `fiscal_app_export/templates/binance_v2.html`
**Decisión arquitectónica:** `docs/decisions/ADR-0002-exchange-template-standalone.md`

---

## Prerrequisitos

Antes de crear la plantilla HTML, estos dos elementos deben existir y estar validados con datos reales:

1. **Clasificador del exchange** (`fiscal_app_export/clasificador_[exchange].py`)
   - Parsea el CSV/Excel exportado por el exchange.
   - Produce operaciones normalizadas que `MotorFIFO` acepta.
   - Probado con datos reales del exchange (ver `ENGINEERING_PRINCIPLES.md` Principio 2).
   - El valor que se pasa como `exchange` en el FormData del frontend debe coincidir exactamente con el identificador que usa el endpoint `/api/analizar` para seleccionar este clasificador.

2. **Identificador del exchange para la API**
   - Confirma qué string se usa en `formData.append('exchange', '...')`. Busca en `app.py` la función `procesar_*` o el `if exchange == '...'` que llama a tu clasificador.

Si alguno de los dos no existe o no está validado, detener aquí. Crear la interfaz antes que el backend no es el orden correcto.

---

## Paso 1 — Crear la plantilla HTML

### 1.1 Duplicar la plantilla de referencia

```bash
cp fiscal_app_export/templates/binance_v2.html \
   fiscal_app_export/templates/[exchange]_v1.html
```

Convención de nombres: `[exchange]_v1.html` (minúsculas, sin guiones). Ejemplos: `kraken_v1.html`, `coinbase_v1.html`, `kucoin_v1.html`.

### 1.2 Elementos a editar

La siguiente tabla lista **todos** los elementos que cambian. No hay más. Todo lo demás (tokens, componentes, comportamiento, JS) es invariable.

| Elemento | Dónde buscarlo | Qué poner |
|----------|---------------|-----------|
| `<title>` | `<head>`, línea ~8 | `Declara [Exchange] en Hacienda — FIFO automático \| Mariano Sevilla` |
| `<meta name="description">` | `<head>`, línea ~9 | Copy SEO específico del exchange |
| H1 — línea 2 del título | `.page-title`, buscar `fiscal de <br>` | `fiscal de <br>` |
| H1 — nombre en acento | `<span class="h-accent">` | Nombre del exchange |
| H1 — línea 3 | Texto tras el span | Mantener `<br>para Hacienda` salvo que el copy lo requiera diferente |
| Subtítulo del Hero | `.hero-sub` | `Sube tu CSV de [Exchange] y obtén el informe FIFO...` |
| Trust Item 1 | Primera `.tb-text` | `Compatible con el CSV oficial de [Exchange]` |
| Trust Item 2 | Segunda `.tb-text` | `Informe FIFO en PDF` (invariable en la mayoría) |
| Trust Item 3 | Tercera `.tb-text` | `Método FIFO conforme al Art. 37.2 LIRPF` (invariable) |
| Trust Item 4 | Cuarta `.tb-text` | `El archivo nunca se almacena` (invariable) |
| Texto principal del Drop Zone | `#dropHint` | `Arrastra aquí tu CSV de [Exchange]` |
| Descripción del CSV | `.dz-hint` | Descripción del contenido esperado sin nomenclatura interna |
| Link tutorial | `#dzTutorial` | URL del vídeo específico del exchange, `target="_blank" rel="noopener"` |
| Benefit cards | Cuatro `.benefit` | Textos adaptados al exchange y su método de exportación |
| Constante `EXCHANGE_PAGE` | `<script>`, inicio del JS | `const EXCHANGE_PAGE = '[exchange]';` — debe coincidir exactamente con el identificador del clasificador |
| Nombre del PDF descargado | `<a id="btnDownload" ... download="...">` | `informe_fiscal_[exchange].pdf` |
| Instrucciones post-análisis | `#instruccionesPost` | Casillas IRPF correctas y pasos específicos del exchange |
| Mensajes de error | Buscar `_err_msgs` o similar en el JS | Textos adaptados a los errores característicos del CSV del exchange |

**Regla sobre el H1:** los `<br>` son deliberados — controlan la distribución de líneas. Tras editar el copy, verificar visualmente que la distribución sigue siendo correcta en desktop (1060px) y en mobile (375px).

**Regla sobre el copy:** ningún nombre interno del exchange en la interfaz. "Transaction History", "Ledgers CSV", "Historial de Operaciones Spot" son nombres del exchange, no del usuario.

### 1.3 Lo que NO se toca

- Tokens CSS (`:root { --bg, --accent, --font-display... }`).
- Estructura del panel (`drop-area → sep → config-row → sep → benefits`).
- Lógica JS de estados (drag, error, loading, done, retry, reset).
- Lógica JS de year chips (detección, selección por defecto, chip "Todos").
- Validación del archivo (tipo, tamaño, columnas vacías) — el JS ya la maneja.
- Sistema responsive y breakpoints.
- Done State y su estructura.
- Footer y navegación (`nav.css` / `nav.js`).
- El guard de autenticación (`/api/me` al cargar).

---

## Paso 2 — Añadir la ruta en `app.py`

### 2.1 Localizar el bloque de rutas de exchanges

Buscar en `app.py` la función `page_binance` (línea ~1658). Las rutas de exchanges están agrupadas en esa zona.

### 2.2 Añadir la nueva ruta

Patrón a seguir — el mismo que usa `/binance` tras la unificación de 2026-06-28:

```python
@app.route("/[exchange]")
@login_required
@limiter.exempt
def page_[exchange]():
    return render_template("[exchange]_v1.html")
```

**No usar `tool.html` ni `EXCHANGE_PAGES`.** Esos son el patrón legacy. Ver `ADR-0002` para el razonamiento.

**No añadir la entrada a `EXCHANGE_PAGES`.** La plantilla standalone no necesita variables Jinja2 desde Flask — el HTML es autocontenido y usa su propio JS para obtener el contexto del usuario vía `/api/me`.

### 2.3 Verificar el endpoint `/api/analizar`

Confirmar que `app.py` ya tiene un `if exchange == '[exchange]':` (o equivalente) que instancia el clasificador correspondiente. Si no existe, el backend devuelverá un error al enviar el formulario — la interfaz estará lista pero el análisis no funcionará.

---

## Paso 3 — Test local

### 3.1 Arrancar el servidor

```bash
cd fiscal_app_export
python3 app.py
# El servidor escucha en el puerto 5050 (el 5000 está ocupado por AirPlay en macOS)
```

### 3.2 Verificar la ruta

```
http://127.0.0.1:5050/[exchange]
```

Comprobar que:
- La página carga (HTTP 200).
- El usuario autenticado ve la herramienta; el no autenticado es redirigido a `/login`.
- No hay errores de consola en el navegador.
- No hay errores 404 en Network (fuentes, CSS, JS).

### 3.3 Flujo completo

1. Subir un CSV real del exchange.
2. Verificar que los chips de año se detectan correctamente.
3. Seleccionar un ejercicio y pulsar "Generar informe →".
4. Verificar que `POST /api/analizar` devuelve 200.
5. Verificar que el panel muestra el Done State.
6. Verificar que "Descargar PDF" funciona (`GET /api/descargar/{token}` → 200).
7. Pulsar "Nuevo análisis" y verificar que el formulario vuelve al estado inicial.

### 3.4 Checklist de validación

Ejecutar el checklist completo de `DESIGN_SYSTEM.md §14` antes de considerar la herramienta lista. Cubre: consistencia visual, responsive, accesibilidad, estados, funcionamiento, auditoría UX y coherencia con el Design System.

---

## Paso 4 — Antes del push

- [ ] No hay errores de consola en ningún estado de la herramienta.
- [ ] No hay errores 404/500 en ningún endpoint relevante.
- [ ] El flujo completo (CSV → año → generar → descargar → nuevo análisis) funciona con datos reales.
- [ ] El checklist de `DESIGN_SYSTEM.md §14` está completado.
- [ ] Ningún anti-patrón de `DESIGN_SYSTEM.md §11` está presente.
- [ ] No se han modificado `motor_fifo.py`, `clasificador_*.py` ya existentes, `generador_pdf*.py`, `generador_xml_721.py`, `custodios_721.py`, `precios_historicos.py`.
- [ ] No se ha tocado `tool.html` ni ninguna ruta de exchange ya existente.

---

## Referencia rápida: qué documento responde a qué

| Pregunta | Documento |
|----------|-----------|
| ¿Qué tokens usar? ¿Qué breakpoints? ¿Qué componentes? | `docs/DESIGN_SYSTEM.md` |
| ¿Por qué no usamos `tool.html`? | `docs/decisions/ADR-0002-exchange-template-standalone.md` |
| ¿Cómo validar el clasificador del backend antes de empezar? | `docs/ENGINEERING_PRINCIPLES.md` Principio 2 |
| ¿Qué módulos están bajo restricción de gobierno? | `CLAUDE.md §5` |
| ¿Qué hay construido hoy en el sistema? | `docs/ARCHITECTURE.md` |
