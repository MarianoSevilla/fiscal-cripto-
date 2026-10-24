# Fase 3 — Trazabilidad e integridad del núcleo FIFO global (laboratorio)

## Alcance mínimo
Se añade el módulo de **solo lectura** `fifo_global_trazabilidad.py`, utilizable
**solo por código interno** después de `calcular_fifo_global(...)` de la Fase 2.
No cambia motor, clasificador, `app.py`, rutas, PDF, tablas, credenciales o
datos de producción. No existe endpoint que invoque este nuevo módulo.

## Contrato
`auditar_fifo_global(resultado, (fuente_binance, fuente_bitvavo))`:
- Recalcula el resultado sobre las **fuentes presentes** para detectar un
  clasificador cambiado después del cálculo. Reaplica todos los bloqueos del
  núcleo anterior y su conciliación de transferencias.
- Construye una cola FIFO **Decimal independiente por activo** y enlaza cada
  venta con **ID de adquisición**, cantidad exacta y coste EUR atribuible
  a cada lote. Compara los lotes, fechas, cantidades, importes de transmisión,
  ganancias y pérdidas con los resultados del motor heredado (float).
- Diferencias superiores a 1e-6 EUR o 1e-12 unidades provocan rechazo.
  Estas tolerancias son de **verificación de consistencia técnica**, no
  reglas de cálculo o redondeo tributario.
- Incluye el SHA-256 que el llamante declara para cada fuente. Las referencias
  `b1:cv:0` son **ID internos del clasificador**, no IDs nativos del exchange.
  El módulo **no recalcula** el SHA contra el CSV físico. Debe hacerlo un
  controlador posterior desde bytes originales si algún día se expone.
- Para Bitvavo correlaciona cada compra, venta y rendimiento con su **fila
  en el DataFrame parseado** y su `Transaction ID`, cuando existe.
  Si se repite un `Transaction ID` entre filas materiales, el proceso se
  bloquea. Filas idénticas sin ID no se deduplican: se **rechazan por ambigüedad**.
  Compras distintas con importes iguales y fecha/ID distinguibles se conservan.
- Las transferencias ya conciliadas conservan la procedencia fiscal del lote:
  no suponen una segunda adquisición. Un booleano de titularidad no es prueba
  verificable de titularidad; se mantiene advertencia explícita.

## Límite esencial
**El resultado `AuditoriaGlobal` devuelve permanentemente
`historial_exhaustivo_acreditado=False` y
`apto_informe_fiscal_publico=False`.**
No se puede inferir exhaustividad de historiales, wallets ni custodios porque
las existencias alcancen a cubrir una venta. Faltan originales verificables,
cobertura temporal contrastable por exchange, posibles movimientos externos
y corroboración de titularidad, y el motor heredado usa float.

La correlación de fila Bitvavo se hace contra la tabla parseada que existe en
memoria, no contra bytes originales conservados de forma inmutable. Binance
sigue identificando lotes por operación clasificada, sin trazabilidad nativa
autenticada de las filas que originaron la operación. **Ninguna de esas
referencias es un justificante fiscal independiente.**

## Criterio de aceptación
- Pruebas sintéticas con los clasificadores reales Binance/Bitvavo.
- Rechazo de lotes/plusvalías manipulados, fuentes modificadas, precios
  inconsistentes y IDs ambiguos.
- Transferencia conciliada conserva el coste histórico sin duplicar lotes.
- Compras legítimas de igual importe no se eliminan.
- Importes y cantidades, incluyendo comisiones EUR, coinciden entre el
  libro Decimal y los resultados del motor.
- Ningún cambio visible para usuarios. Antes de fusionar esta fase:
  CI completa sobre su HEAD, revisión adversarial independiente y autorización
  expresa del propietario; nunca desplegar ni activar informes globales
  sin autorización adicional.
