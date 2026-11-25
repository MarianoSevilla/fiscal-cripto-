# MVP de créditos FIFO — alcance, tarifas y salvaguardas

**Estado:** infraestructura en rama de revisión; desactivada por defecto. No hay compras reales, cobros ni cambio productivo.

## Tarifas piloto propuestas

Los percentiles aportados de PostgreSQL (P50 442, P75 2.292, P90 6.298, P99 33.519 filas) sirven para dimensionar bandas, no para prometer coste de CPU ni suficiencia fiscal.

| Paquete | Precio final de referencia | Créditos | Uso orientativo |
|---|---:|---:|---|
| Básico | 15,90 € | 110 | Hasta un análisis P75; dos análisis P50 aproximados |
| Estándar | 29,90 € | 230 | Un análisis P90 y margen pequeño para archivos adicionales |
| Avanzado | 49,90 € | 460 | Un análisis P99 incluso con el máximo recargo multarchivo |

Crédito por análisis: hasta 1.000 filas = 50; 1.001–3.000 = 100; 3.001–10.000 = 200; 10.001–35.000 = 400. A esto se añaden 10 créditos por cada CSV adicional al primero, con máximo de 60. Así se mantiene visible la diferencia entre volumen de filas y factor operativo multarchivo. El número de archivos es una aproximación provisional de complejidad; no representa complejidad fiscal ni tiempo de CPU medido. Más de 35.000 filas no recibe cotización automática.

Esta escala hace que Avanzado cubra el precio máximo de un análisis de 35.000 filas y 60 créditos multarchivo (400 + 60). Básico y Estándar cubren, respectivamente, las bandas próximas al P75 y P90 sin multiplicar créditos gratuitos. Los créditos equivalen, respectivamente, a 0,1445 €, 0,1300 € y 0,1085 € de precio bruto por crédito. La ventaja unitaria del paquete superior es moderada y mantiene una escalera clara.

Los importes de paquete permanecen como hipótesis editables en `credit_pricing.py`, no como precio comercial aprobado. El consumo, los límites de filas y el recargo deben revisarse tras el piloto con tiempos, errores y soporte observados. El coste real de procesamiento por tamaño aún no está medido.

## Regla de cargo y correcciones

- La validación y cotización son gratuitas. La cotización se firma en servidor y se liga al usuario, ejercicio, exchange y huella SHA-256 de los archivos; la ejecución debe volver a presentar exactamente los mismos archivos.
- La autorización explícita reserva como máximo la cotización. El resultado definitivo o provisional útil liquida la reserva. Cualquier otro resultado libera la reserva. Solo se muestra «No se han consumido créditos. Tu saldo permanece intacto» tras confirmar la liberación; en caso de incertidumbre se bloquea el monedero y se indica que contacte con soporte.
- Los errores y reintentos técnicos no consumen créditos. Un resultado provisional consume el precio autorizado porque se completa un análisis útil; nunca se presenta como apto para declarar.
- Una descarga repetida no consume créditos. Los PDF adquiridos se guardan cifrados con AES-256-GCM, asociados a una cuenta y análisis, durante 365 días. No se guardan los CSV. Tras esa ventana el PDF deja de estar disponible; conservarlo más tiempo o regenerarlo sin coste requeriría cambiar esta política antes de activar el piloto.
- Se permite una corrección gratuita del mismo informe dentro de 30 días. La primera corrección se vincula al informe original; no se encadenan correcciones gratuitas. Otra corrección o un análisis distinto se cotiza normalmente. Esta limitación busca equilibrio económico y debe validarse antes de la oferta pública.

## Stripe, saldo y reembolsos

Checkout utiliza `mode=payment` y cantidades fijas derivadas del catálogo del servidor. La concesión se produce solo tras verificar la firma del webhook y comprobar modo test, sesión, estado de pago, importe, moneda y compra. La URL de éxito no concede créditos. Los handlers deduplican por compra/evento y las transiciones de saldo usan bloqueos transaccionales PostgreSQL.

Un evento de reembolso no resta créditos a ciegas: congela el monedero y marca la compra para revisión manual, porque parte de los créditos podría haberse gastado. El saldo se conserva hasta conciliación. Las compras no crean renovaciones. Los créditos comprados no caducan y pueden acumularse; por tanto, el efectivo cobrado por paquetes sin consumir representa una obligación y no beneficio realizado.

## Punto de equilibrio orientativo

Hipótesis solicitadas: 700 €/año de costes fijos, 2 € de coste variable por compra, comisión Stripe de 1,5 % + 0,25 €, mezcla de ventas 60/25/15 y precios con IVA incluido. Para estimar ingreso neto se supone IVA español general del 21 %; el asesor contable debe confirmar tratamiento y factura antes de vender.

| Paquete | Neto sin IVA supuesto | Stripe aprox. | Coste variable | Contribución por compra |
|---|---:|---:|---:|---:|
| Básico | 13,14 € | 0,49 € | 2,00 € | 10,65 € |
| Estándar | 24,71 € | 0,70 € | 2,00 € | 22,01 € |
| Avanzado | 41,24 € | 1,00 € | 2,00 € | 38,24 € |

La contribución ponderada es aproximadamente 17,63 €/compra. El punto de equilibrio de caja frente a 700 € fijos es 39,7, es decir, unas **40 compras anuales**, antes de remuneración del trabajo, soporte no medido, mantenimiento, amortización y créditos no consumidos. Con 40 compras, la contribución estimada después de costes fijos es apenas 5,22 €. No es una previsión de beneficio ni de demanda: el importe fijo y los 2 € son hipótesis, no facturación histórica.

| Compras/año con esa mezcla | Contribución menos 700 € fijos |
|---:|---:|
| 40 | 5 € |
| 60 | 358 € |
| 100 | 1.063 € |

El beneficio económico será inferior al punto de equilibrio de caja cuando se contabilice el trabajo del propietario, soporte, mantenimiento, gestoría, amortización y obligaciones de paquetes cuyo saldo siga sin usarse. No se ha obtenido aquí una conversión real de usuarios activos a compradores ni coste de análisis por percentil; no se presentan como datos.

## Activación

Todos los accesos de compra y consumo exigen simultáneamente `FIFO_CREDITS_ENABLED=true`, `FIFO_CREDITS_TEST_MODE=true`, una clave Stripe `sk_test_`, un secreto de webhook test `whsec_` y una clave de cifrado aleatoria de 32 bytes para PDF. Sin estas condiciones el flujo permanece desactivado. La migración amplía el esquema y el gate de arranque; hay que aplicar y verificar la migración de manera separada antes de desplegar el código. Esta PR no incluye cambios Railway, secretos, Stripe ni producción.

Antes de habilitar un piloto comercial quedan por aprobar precios/consumos, retención de informes de 365 días, política de una corrección gratuita, facturación/IVA, textos de compra y privacidad, procedimiento manual de conciliación de reembolsos y gestión/rotación/recuperación de la clave de cifrado. La imposibilidad de recuperar esa clave implicaría perder la capacidad de descargar los informes almacenados.
