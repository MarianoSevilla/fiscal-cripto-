# FIFO multiarchivo — Contrato de la primera entrega (19/10/2026)

**Estado:** implementación parcial de Fase 1, aislada. No consolidación entre exchanges, no controles de licencia, no despliegue.

## Regla fiscal y comercial

- Para calcular el resultado de un ejercicio pueden requerirse operaciones de ejercicios anteriores.
- Procesar los ficheros completos necesarios y filtrar la **salida**, nunca calcular un FIFO con historial truncado.
- Los CSV de un mismo exchange pueden representar periodos separados, versiones corregidas o diferentes secciones. No se prohíbe repetir importación ni se toma como fraude.
- El programa **no presume** que un CSV pertenece al titular: deduplicación fiscal y verificación de origen son responsabilidades independientes.
- Un ID de operación en un CSV editable solo ayuda a reconocer transacciones; no certifica la propiedad del fichero.

## Matriz de formatos / alcance

| Exchange | Situación actual y decisión de esta entrega |
|---|---|
| Kraken | **Nuevo:** combinar entre 2 y 8 ledgers CSV con txid; repetir la misma fila deduplica, conflicto de txid rechaza |
| Bitvavo | **Nuevo:** combinar CSV con Transaction ID, si el campo está presente en todos |
| Coinbase | **Nuevo:** combinar CSV con ID, aceptando metadatos anteriores a la cabecera; mismo esquema |
| Uphold | **Nuevo:** combinar CSV con Id; mismo esquema |
| KuCoin | Conservar el flujo especializado multifuente ClasificadorKuCoin, sin alterar reglas actuales |
| Bitget | Conservar ClasificadorBitgetMulti, incluido Order no. y conciliación entre subformatos; no alterar |
| Binance | Pendiente: formatos históricos y TX, User ID opcional; unir periodos sin ID exige reglas contra coincidencias ambiguas |
| Nexo | Pendiente: comprobar unicidad/estabilidad del campo Transaction con fixtures representativos |
| Crypto.com | Pendiente: Transaction Hash puede representar patas distintas; no asumir unicidad por fila |
| MEXC | Pendiente: XLS/XLSX y distintos tipos de libro requieren combinación específica |
| Bit2Me | Pendiente: CSV fiscal vertical de origen y Excel estimativo no deben mezclarse |

## Invariantes de la primera implementación

1. El **flujo de un solo CSV permanece intacto** para todos los exchanges.
2. No mezclar exchanges ni cabeceras distintas. La estructura de columnas debe ser equivalente; su orden puede variar.
3. Exigir ID nativo no vacío en toda fila; deduplicar únicamente por **mismo ID y fila completa idéntica**.
4. Si un mismo ID aparece con contenido distinto, detener antes de producir el PDF; no elegir una versión unilateralmente.
5. No deduplicar por fecha, precio y cantidad: dos operaciones independientes pueden tener valores idénticos.
6. Permitir periodos sin solapamiento. Su ausencia de coincidencias no prueba titularidad distinta.
7. Respetar límite global de petición (15 MiB), tamaño por archivo (10 MiB), máximo de 8 CSV y filas ya limitadas por backend.
8. Los archivos subidos y el combinado son temporales; se borran en el bloque de limpieza de la petición.
9. Usar el parser y el motor FIFO de siempre para el conjunto unido; no implementar motor paralelo.
10. El usuario conoce el error y puede corregir sus exportaciones; no hay compra, bloqueo comercial ni registro de supuesta infracción.

## Pruebas y límites

- Pruebas unitarias sintéticas del módulo: igualdad exacta, solapamientos, periodos independientes, cabeceras reordenadas, ID ausente, conflicto y fila malformada.
- **Pendientes antes de fusión:** regresión de integración de las cuatro rutas reales (CSV único vs combinación equivalente), pruebas de browser, límites de tamaño, fixtures representativos, CI total, rendimiento y compatibilidad con archivos de producción sin extraer PII.
- No se ha demostrado que las variantes reales de los cuatro exchanges siempre contengan ID; si no lo incluyen, el modo multiarchivo rechaza y el modo individual continúa disponible.
- El reconocimiento de fuentes para control de titularidad (D1) será otro componente: no reutilizar automáticamente las claves de deduplicación como prueba de propiedad.
- Las importaciones de diferentes exchanges **siguen generando cálculos separados**. No anunciar FIFO global hasta que exista motor de consolidación entre plataformas y pruebas fiscales.

## Siguiente entrega técnica (no autorizada en esta PR)

Probar los casos especiales de Binance, Nexo, Crypto.com, MEXC y Bit2Me, extender el tratamiento según evidencia; implementar posteriormente el motor FIFO multiexchange en otra rama/PR.
