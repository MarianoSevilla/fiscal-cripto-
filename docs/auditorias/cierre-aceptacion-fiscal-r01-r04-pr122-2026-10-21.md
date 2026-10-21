# Cierre de aceptación fiscal R01–R04 — PR #122

**Corte:** 2026-10-21. **Base de auditoría:** PR #122, commit `4143b408195ab78fa05ff5a08aacd0398a5074cf` (código, antes de añadir este acta). **Entorno:** rama aislada, no producción.

## Dictamen ejecutivo

**NO-GO para fusión, despliegue y comercialización de la PR #122 tal como está.**

Este dictamen **cierra la investigación y la aceptación del alcance R01–R04**, no cierra la PR mediante fusión ni acredita ausencia de defectos. Se conservan las mejoras como trabajo no publicado. No proseguir la implementación dentro de este ciclo.

**CI comprobada:** Required CI #39567324547 = success, incluyendo backend, postgres-bootstrap y browser-navigation. El job `postgres-bootstrap` no equivale a una prueba fiscal de extremo a extremo sobre PostgreSQL. Los escenarios E2E de persistencia emplean una SQLite temporal y datos sintéticos. La API del proveedor de cotizaciones fue simulada: no se ha comprobado una licencia contratada ni la cobertura de precios reales.

## Matriz de aceptación — comprobado vs. no acreditado

| Caso | Comportamiento del código de PR #122 | Evidencia disponible | Dictamen comercial |
|---|---|---|---|
| Compra EUR + venta EUR con historial FIFO completo | Calcula resultado fiscal y genera PDF | Pruebas unitarias, HTTP 200 y persistencia sintética; pruebas anteriores F01–F07 | Candidato; no supone garantía universal por formato |
| Venta sin compras anteriores | HTTP 422, sin PDF/token y registro `failed` | Pruebas directas/HTTP/SQLite | Rechazo seguro para los casos probados |
| Venta con inventario parcial | HTTP 422, sin PDF/token de éxito | Pruebas directas/HTTP/SQLite | Rechazo seguro para los casos probados |
| Permuta cripto/cripto sin comisiones, con ambas cotizaciones EUR horarias y timestamp fiable | Mayor valor de mercado, nueva base FIFO, registro de fuentes y fechas; filtro de ejercicio | Oráculos sintéticos, PDF real extraído, pruebas HTTP | Candidato condicionado a cobertura/licencia del proveedor |
| Permuta con cotización incompleta, desactualizada o ticker desconocido | HTTP 422 | Pruebas sintéticas/HTTP | Rechazo seguro probado |
| Permuta Coinbase con subtotal EUR ambiguo | No utiliza subtotal como única prueba del mercado de una pata | Prueba sintética | Requiere cotizaciones independientes |
| Permuta Kraken con fee en `spend` o `receive` | Conserva ambas monedas e importes de comisión, bloquea positiva no conciliada | Prueba de ledger pareado sintético | No comercializar hasta determinar imputación fiscal y bruto/neto |
| Permuta Uphold con fee | Conserva fee estructurada y bloquea | Prueba de CSV sintético | No comercializar hasta tratamiento fiscal justificado |
| Coinbase Convert con `Fees and/or Spread` positivo | Bloqueo conservador: no distingue spread incorporado del gasto deducible | Caracterización de código, prueba parametrizada por importe de fee | No comercializar hasta separar conceptos |
| Permuta Bitget/KuCoin con fecha sin huso verificable | Bloqueo preventivo para evitar cotizar hora equivocada | Pruebas sintéticas | No comercializar; origen UTC requiere normalización verificable |
| Nexo con equivalentes USD sin conversión EUR acreditada | Rechazo 422 cuando se detecta el caso | Pruebas directas/HTTP/SQLite | No comercializar escenario afectado |
| Uphold Brave Rewards sin EUR en fecha de recepción | Rechazo 422 | Pruebas directas/HTTP/SQLite | No comercializar escenario afectado |
| Modelo 721 | No utiliza el nuevo validador/valorador IRPF | Inspección de flujo y regresiones existentes | Fuera del alcance de aceptación de esta PR |

## Riesgos residuales y decisión de cierre

1. **Proveedor externo:** CoinGecko requiere condiciones de licencia comercial, atribución y verificación real de antigüedad, precisión, símbolos y cuotas. No se ha contratado ni probado una cuenta pagada. El límite actual de ocho consultas por análisis puede rechazar historiales legítimos.
2. **Comisiones:** la detección de fees se ha reforzado en Coinbase, Kraken y Uphold. No hay tratamiento numérico fiscal independiente y completo para todos los formatos, las monedas de fee, la imputación bruto/neto y los spreads. La cobertura de otros clasificadores no está certificada.
3. **Zona horaria:** los parsers Bitget/KuCoin pueden eliminar el offset de origen. Se rechazan permutas en vez de valorar con hora inferida; aún falta normalización válida.
4. **Historiales ajenos a pruebas:** los resultados son sintéticos; no se ha establecido una cobertura representativa de casos reales con permiso del usuario, ni una prueba HTTP fiscal con PostgreSQL.
5. **Experiencia del cliente:** no existe una interfaz aprobada para aportar cotizaciones históricas documentadas cuando faltan datos. Un fallo del proveedor provoca rechazo del informe.
6. **Compatibilidad y alcance:** `main` cambió después de la base inicial de PR #122 por un commit de iconos estáticos (#123). Debe revalidarse cualquier integración posterior sobre el `main` efectivo.

## Decisión operativa

- **Cerrar este ciclo de auditoría sin fusionar la PR #122.**
- **Mantener #122 como borrador técnico de referencia, no como trabajo listo para publicar.** No añadir nuevos cambios al alcance cerrado.
- **No habilitar cobro por escenarios de permutas no certificados.**
- **Continuar usando producción sin introducir este nuevo valorador**, manteniendo sus limitaciones actuales explícitas; no declarar que la plataforma actual carece de riesgos fiscales.
- **La próxima revisión estratégica del proyecto será una nueva decisión de producto**, separada de este cierre: priorizar cobertura/ingresos frente a costes reales del proveedor y de implementación, y seleccionar un MVP fiscal acotado. No abrir ese estudio ahora.

Este acta distingue pruebas satisfactorias de aceptación fiscal y deja documentado por qué un workflow verde no equivale a autorización de fusión o de comercialización.
