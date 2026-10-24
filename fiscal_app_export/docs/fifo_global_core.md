# Núcleo FIFO global Binance + Bitvavo — Fase 2 (laboratorio)

## Alcance aprobado
Módulo `fifo_global.py` **interno y desconectado**: no añade rutas HTTP,
pantallas, PDF, pagos, tablas SQL ni tareas de Railway. Las herramientas
individuales conservan exactamente sus flujos.

Entradas: dos clasificadores ya ejecutados (Binance TX/clásico y Bitvavo),
identidad de titular, huella SHA-256 de cada archivo, zona horaria del CSV y
ejercicio de salida. La identidad debe corresponder al usuario autenticado
cuando exista un futuro endpoint; la huella debe derivarse de los bytes
recibidos, nunca de un valor enviado por el navegador.

Cálculo: validación material fail-closed, normalización a instantes UTC,
ordenación global, conciliación explícita de movimientos de cripto propias,
un solo `MotorFIFO` para todo el histórico y filtro de resultados a un
ejercicio sin borrar lotes ni resultados históricos del cálculo base.

## Seguridad y restricciones vigentes

- Solo Binance y Bitvavo, una fuente de historial por exchange en esta primera entrega.
- Solo compraventas con importe **EUR** explícito; comisiones no EUR, swaps y
  rendimientos sin EUR acreditado son incompatibles con emitir resultado.
- El export Bitvavo debe declarar `Timezone=UTC` en todas las filas.
  Binance exige un dato de zona conocido y explícito (UTC u offset fijo).
  Fechas sin hora fiable o con un desfase estacional no demostrado requieren
  rechazo o revisión antes de integrarse.
- Los movimientos de cripto (depósitos/retiradas) deben emparejarse mediante
  identificadores explícitos y evidencia de mismo titular ya verificada por
  el controlador. Los emparejamientos que difieran de cantidad, activo,
  intervalo temporal o identidad son rechazados. **Nunca** se deduce la
  titularidad comparando únicamente cantidades. Las comisiones de red aún
  no están admitidas y fuerzan rechazo.
- Las compras de stablecoins recogidas como movimientos, los traspasos de
  tipo ambiguo y las filas desconocidas bloquean la emisión global.
- Dos operaciones realmente distintas de importes iguales no se deduplican.
  Se rechazan archivos de huella idéntica y fuentes con identidad duplicada.
  Los formatos que carezcan de IDs nativos no permiten acreditar por sí solos
  la ausencia de operaciones solapadas entre descargas parciales.
- El código no demuestra que se haya importado **todo** el historial del
  contribuyente, ni todos sus custodios, wallets ni ejercicios anteriores.
  Verificar esa cobertura es condición pendiente para un informe certificable.
- Se conserva trazabilidad de cada operación normalizada hasta el origen,
  pero falta vincular de forma auditable cada lote consumido a la fila nativa
  y revisar redondeo de `float` del motor heredado.

## Criterio de aceptación de esta PR

Tests adversariales con CSV sintéticos genuinamente parseados por ambos
clasificadores; caso compra Binance/venta Bitvavo, orden UTC, coste EUR,
filtrado por ejercicio, comisiones, sin inventario previo, rendimientos,
fuentes repetidas, transferencias confirmadas y bloqueos materiales.

**No habilitar** descarga, JSON de éxito ni UI global por esta PR. No
fusionar/desplegar sin autorización expresa y CI completa sobre su HEAD.
