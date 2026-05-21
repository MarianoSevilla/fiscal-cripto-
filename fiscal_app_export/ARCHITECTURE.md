# Arquitectura — Herramienta Fiscal Cripto

## Principio de validación del Modelo 721

El sistema separa explícitamente tres capas independientes de validación:

### 1. Técnica
El XML está bien formado y valida contra el XSD oficial de la AEAT.
Verificable con `validar_xml_contra_xsd()` en `generador_xml_721.py`.

### 2. Estructural
Todos los campos requeridos existen y contienen datos válidos según el esquema del modelo. Los placeholders, datos incompletos o identificadores no verificados impiden considerar el XML como definitivo.

> Ejemplo: `IDOtro` con `ID="PENDIENTE"` / `IDType="06"` es XSD-válido pero estructuralmente incompleto.

### 3. Fiscal
La información tiene suficiente fiabilidad material para ser presentada ante Hacienda. Esto incluye coherencia FIFO, precios históricos razonables, custodios identificados y ausencia de advertencias críticas.

---

**El sistema nunca colapsa estas tres capas en una única validación.**

Un XML puede ser técnicamente válido (capa 1) y estructuralmente correcto (capa 2), y seguir marcado como `BORRADOR` si la validación fiscal (capa 3) no está resuelta.

**Regla de oro: "el XML pasa XSD" no equivale a "listo para presentar".**

---

## Estados del XML

| Estado | `xml_generable` | `es_borrador` | Significado |
|--------|:-:|:-:|---|
| `BLOQUEADO` | `False` | — | No se puede generar el XML. Falta precio de algún activo, NIF del declarante inválido, u otro bloqueante crítico. |
| `BORRADOR` | `True` | `True` | XML generado pero con datos incompletos o no verificados. No presentar sin resolver los pendientes. |
| `LISTO` | `True` | `False` | Todos los datos presentes y verificados. Revisar antes de firmar y presentar. |

---

## Flujo del Modelo 721

```
CSV del exchange
      │
      ▼
ClasificadorXxx  ──►  MotorFIFO  ──►  generar_datos_modelo_721()
                                              │
                               enriquecer_721_con_precios()
                                              │
                                       validar_para_xml()  ──►  ValidacionXML
                                              │                  (capas 1+2+3)
                                       generar_xml_721()
                                              │
                                       ┌──────┴──────┐
                                  BLOQUEADO     BORRADOR / LISTO
                                  (sin XML)     (XML generado)
```

## Archivos clave del módulo 721

| Archivo | Responsabilidad |
|---|---|
| `modelo721.py` | Snapshot de posición a 31/12, estructura de datos |
| `generador_xml_721.py` | Generación del XML según XSD AEAT, validación de las tres capas |
| `custodios_721.py` | Base de datos de custodios extranjeros (nombre legal, NIF, país, confianza) |
| `precios_historicos.py` | Obtención y caché de precios EUR a 31/12 (CoinGecko/BCE) |
| `app.py → /api/721` | Endpoint POST: orquesta el flujo completo y emite métricas de uso |
| `static/modelo721.html` | Frontend: formulario, tres estados visuales, descarga XML |
| `xsd/` | Schemas XSD oficiales de la AEAT para validación local |

## Observabilidad

El endpoint `/api/721` emite una línea de log estructurada por petición con etiqueta `M721`:

```json
{
  "event": "721_generado",
  "exchange": "bitvavo",
  "ejercicio": 2024,
  "estado": "borrador",
  "n_activos": 3,
  "xml_generable": true,
  "xml_es_borrador": true,
  "por_debajo_umbral": false,
  "tickers_sin_precio": [],
  "n_custodios_sin_id": 1,
  "n_bloqueantes": 0,
  "n_advertencias": 2,
  "xml_generado": true,
  "total_eur_aprox": 79950.0
}
```

No se loguean: NIF, nombre del declarante, operaciones individuales, cantidades exactas por activo, ni el XML generado.

Para analizar: `grep "M721" app.log | jq -s 'group_by(.exchange)'`
