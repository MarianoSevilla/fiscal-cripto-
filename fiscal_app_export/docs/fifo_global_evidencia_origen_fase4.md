# Fase 4 — Evidencia de origen del FIFO global (laboratorio)

## Qué se entrega
`fifo_global_evidencia_origen.py` añade una **comprobación opcional,
solo en memoria y sin efectos externos** después de la Fase 3:
`verificar_origen_fifo_global(resultado, fuentes, archivos_por_source_id)`.

- Calcula el SHA-256 de los **bytes originales aportados** y rechaza cualquier
  discrepancia con la huella declarada en `FuenteGlobal`. Ningún hash de un
  campo remitido por el navegador se toma como prueba suficiente.
- Lee CSV UTF-8 con reglas estrictas y vincula cada compraventa admitida con
  la **línea final física del registro CSV**. En Binance, una operación puede
  necesitar dos filas (Transaction Buy + Transaction Spend), además de una
  comisión; no se inventa un identificador nativo donde no existe.
- Contrasta activo, fecha UTC, sentido de la operación, cantidad, importe EUR
  y comisión con el cálculo normalizado. En Bitvavo coteja además el
  `Transaction ID` del archivo con la evidencia de Fase 3.
- Contrasta **todas las columnas originales de Bitvavo** con la tabla cargada
  por el clasificador, incluso aquellas que no modifican la cantidad FIFO,
  como Address o diferencias de Quote Price ocultas por redondeo. En Binance
  compara el multiconjunto de filas originales contra el DataFrame parseado,
  incluyendo Cuenta, Observación, tipo, moneda, fecha y cambio. No permite
  tratar un hash recalculado sobre otro CSV como si fuese el origen de las
  operaciones clasificadas.
- Devuelve la primera y última fecha observadas **por fuente**, sin inferir
  que el intervalo intermedio esté completo.
- Reejecuta la auditoría de lotes de Fase 3 y nunca modifica el cálculo.
  `RevisionOrigen` marca siempre
  `historial_exhaustivo_acreditado=False`,
  `titularidad_acreditada=False` y `apto_informe_fiscal_publico=False`.

## Contrato limitado y rechazo conservador
Esta **primera implementación** solo acepta:
- **Binance CSV clásico en español:** columnas `Tiempo, Operación, Moneda,
  Cambio, Cuenta, Observación`; pares inequívocos `Transaction Buy` +
  `Transaction Spend` valorados directamente en EUR, y una `Transaction Fee`
  opcional, únicamente en EUR. Un mismo instante con múltiples compras/gastos,
  así como otros movimientos y formatos Binance TX recientes, se rechaza.
- **Bitvavo CSV:** encabezado conocido; `Timezone=UTC`, estado
  `Completed`/`Distributed`; compraventas `buy`/`sell` con contraparte y
  precio en EUR, comisión en EUR. Dentro del contrato **CSV clásico**
  se exige `Amount` positivo en compras y negativo en ventas; el importe
  `Received / Paid Amount` tiene sentido opuesto. Se contrasta que la
  cantidad original y el producto cantidad × precio sean coherentes con
  el importe EUR, con tolerancia derivada de la precisión decimal textual
  del archivo y el redondeo del clasificador a 10 decimales; no se usa
  un porcentaje arbitrario. Se rechazan formatos numéricos ambiguos,
  sin asumir compatibilidad universal con exportaciones históricas.
  Los rendimientos, transferencias, órdenes
  canceladas y otros eventos quedan **fuera de este subconjunto acreditado**;
  no se procesan silenciosamente.

Los rechazos **no indican necesariamente un error fiscal del usuario**:
significan que este laboratorio aún no posee una correspondencia documental
suficiente para ese formato. Se evita sobreinterpretar o falsear un resultado.

La correlación de Binance para operaciones simultáneas/heterogéneas no dispone
de un ID universal fiable; la coincidencia de cantidad y fecha tampoco prueba
por sí sola la autenticidad de los archivos. El fichero máximo por fuente es
25 MiB en este subconjunto, como límite defensivo de memoria.

## Limitaciones que impiden publicar
Un SHA-256 calculado sobre bytes **proporcionados por el solicitante** solo
demuestra consistencia con esos bytes, no procedencia acreditada de Binance
o Bitvavo ni que el histórico aportado esté completo. El rango de fechas
observado no prueba cobertura sin saltos ni existencia/ausencia de otras
cuentas, wallets o plataformas. Esta fase tampoco comprueba titularidad real
con documentos ni resuelve todos los formatos históricos Binance/Bitvavo.

**No se dispone de exportaciones reales consentidas en este encargo**:
las pruebas de CI usan CSV sintéticos. Para validar exportaciones reales se
requieren archivos autorizados, tratamiento minimizado de datos personales,
comparación de resultados con justificantes y registro de cualquier formato
no reconocido. No incorporar archivos personales al repositorio ni logs.

## Integración y permisos
No cambia Flask, PostgreSQL, MotorFIFO, clasificadores, interfaz, PDF, pagos
ni producción. El módulo carece de rutas HTTP. La PR debe superar CI completa
y auditoría adversarial independiente; no fusionar ni desplegar sin
autorización expresa del propietario. Un eventual merge sigue **sin
autorizar informes fiscales globales para clientes**.
