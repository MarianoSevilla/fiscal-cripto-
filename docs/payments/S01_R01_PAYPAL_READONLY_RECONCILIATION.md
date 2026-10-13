# S01-R01 — Inventario local de evidencias PayPal y conciliación histórica

**13/10/2026 · Etapa E1 de [matriz S01 G05](https://github.com/MarianoSevilla/fiscal-cripto-/pull/46)**

**Estado: SOLO PREPARACIÓN TÉCNICA. NO-GO para cierre financiero, merge, deploy, webhooks ni cobros.** Código/aplicación de PayPal retirados en #41, pero su retirada **no prueba** que no existan órdenes, capturas, abonos, reembolsos o eventos pendientes.

## 1. Evidencia y límites de este encargo

- Fuente de campos: `FiscalAdvisoryRequest` en `fiscal_app_export/models.py`, rama de PR #45: `paypal_order_id`, `paypal_capture_id`, `payment_provider`, `amount_paid`, `currency`, `paid_at`, `status`, `is_test`, `quote_accepted_at`, y referencias Stripe para detectar incoherencias.
- Base: PR #45 `9086bee60b52d0cde269ad06bb8388b60125873c` (stack #41→#43→#44→#45), no `main`. No tocar #29 U04 ni su rama Alembic paralela.
- El propietario **ya acreditó** integridad SHA-256 y ejecución satisfactoria de Alembic sobre un dump local restaurado. Eso valida compatibilidad de migraciones, **no conciliación de dinero**.
- La única copia conocida aquí del respaldo es de **10/10/2026**. El extracto será un corte histórico; no acredita pagos o eventos posteriores hasta la fecha de reconciliación.
- No se solicita ni almacena en GitHub/ChatGPT el respaldo, DNI/NIF, emails, nombres, direcciones, tokens, `paypal_order_id`, `paypal_capture_id`, importes individuales, capturas de Dashboard, registros HTTP o credenciales.

## 2. Instrumento local preparado

`fiscal_app_export/tools/s01_paypal_inventory_local.py`:

1. Reutiliza `checked_archive`, `expected_digest`, `verify_pg18`, `run_step` y la conexión Unix de la PR #45, sin modificarla.
2. Exige archivo `pg_dump` custom privado 0600, dueño del usuario, SHA-256 preexistente, PostgreSQL 18 local y proceso **no-root**. Rechaza ejecución dentro de GitHub Actions y entornos con variables de proveedor `RAILWAY_*`, `STRIPE_*` o `PAYPAL_*`.
3. Inicializa una **instancia PG18 temporal nueva**, privada y sin TCP, y restaura el respaldo mediante transacción completa. No utiliza ninguna `DATABASE_URL` o `PGPASSWORD` heredada. No importa `app.py` ni corre Alembic ni `db.create_all()`.
4. Confirma `data_directory` de la instancia efímera y revisión `v5w6x7y8z9a0`. Solo sobre esa conexión activa **`READ ONLY` / `REPEATABLE READ`** para consultar las tablas históricas. No ejecuta DML ni llamadas a proveedores.
5. Solo publica **recuentos fijos** (consultas `COUNT(*) FILTER`) y número de grupos de IDs duplicados (`COUNT(*)` exterior), sin extraer los valores de identificación. No agrupa por nombres, correos ni documentos, ni presenta ningún registro individual. Devuelve una indicación expresa de que G05 sigue ABIERTO.
6. Detiene el clúster y borra solo su directorio efímero si el apagado se confirma. Si no puede confirmarse el apagado, preserva la carpeta privada para evaluación; nunca elimina la copia original.
7. No entrega importes monetarios ni suma montos de pagos: **el importe local no es evidencia suficiente de liquidación PayPal**.

### Recuentos disponibles

| Señal (salida `S01 R01`) | Interpretación limitada |
| --- | --- |
| `expedientes_totales` | Número de expedientes conservados en el dump |
| `expedientes_senal_paypal` | Al menos orden/captura PayPal o `payment_provider=paypal` |
| `paypal_orden_presente`, `paypal_captura_presente` | Presencia de referencias, **no** estado de cobro |
| `paypal_orden_sin_captura` | Orden local sin ID de captura; **puede** haberse capturado con ACK perdido |
| `paypal_captura_sin_orden` | Referencia de captura sin orden; inconsistencia que requiere revisión |
| `paypal_proveedor_sin_ambos_ids` | Marcado PayPal sin referencias locales |
| `paypal_con_importe_local`, `paypal_con_paid_at` | Registro de importe/fecha local; puede estar incompleto o equivocado |
| `paypal_estado_paid_received`, `paypal_estado_refunded` | Estado local, no evidencia definitiva del proveedor |
| `paypal_sin_captura_con_senal_pago` | Marca de pago/refund pero sin captura: cuarentena provisional |
| `paypal_senal_is_test`, `paypal_senal_no_test` | División por `is_test`; el flag **no prueba** sandbox vs Live |
| `paypal_divisa_no_eur_o_nula` | Divisa no EUR o ausente; no presupone error |
| `paypal_id_*_vacio_no_nulo` | Referencia vacía, dato de calidad incorrecta |
| `paypal_ids_con_proveedor_stripe` | Señales PayPal y Stripe contradictorias; revisar sin corregir |
| `pagado_sin_proveedor_ni_ids` | Posible actividad no trazada, con proveedor/IDs vacíos |
| `aceptados_sin_proveedor_ni_ids` | Presupuesto aceptado sin proveedor/IDs; **no presupone cobro** |
| `paypal_grupos_id_*_repetidos` | Número de valores de orden/captura repetidos entre expedientes; **no** imprime valores |

Un registro puede pertenecer a **varios recuentos simultáneamente**. Nunca sumar columnas como si fueran clientes únicos. El código interpreta como ausente una referencia `NULL` o cadena en blanco, pero cuenta separadamente blancos no nulos.

## 3. Pruebas sintéticas

- `test_s01_paypal_inventory_contract.py`: solo consultas agregadas/whitelist, rechazo de columnas arbitrarias y transacción READ ONLY obligatoria.
- `qa_s01_paypal_inventory_pg18.py`: crea una DB PG18 **ficticia** de CI, inserta 9 expedientes totalmente inventados (incluye duplicados, capturas sin orden, pagos sin referencias, flags de TEST y Stripe) y comprueba los **22 recuentos exactos**. Comprueba además que una instrucción `UPDATE` falla con `ReadOnlySqlTransaction`.
- `.github/workflows/required-ci.yml`: ejecuta esta QA dentro del job PostgreSQL 18. Sin secrets, permisos nuevos, env externo ni conectividad a PayPal.

La CI prueba SQL y seguridad sobre **datos sintéticos**; no incluye el backup real del Mac.

## 4. Procedimiento para el propietario (solo después de CI verde)

En el Mac mini, con entorno virtual ya preparado, el propietario podrá actualizar esta rama y ejecutar **primero un preflight**:

```bash
cd "$HOME/s01-rehearsal-source"
# Utilizar una nueva copia local de trabajo o cambiar a la rama auditada
# solo si el árbol Git está limpio y se ha comprobado el SHA autorizado.
source .venv/bin/activate

BACKUP="$HOME/railway-backups/fiscal-cripto-production-20261010-234816.dump"
SHA_FILE="$BACKUP.sha256"
PG_BIN="$(brew --prefix postgresql@18)/bin"

python fiscal_app_export/tools/s01_paypal_inventory_local.py \
    --backup "$BACKUP" --sha-file "$SHA_FILE" \
    --pg-bin "$PG_BIN" --preflight-only
```

Tras aprobar la CI y el preflight se podrá ejecutar una segunda vez **sin** `--preflight-only` para obtener contadores históricos. **No hacerlo en esta fase sin confirmar el SHA validado**. Evitar copiar datos privados o salida de herramientas de diagnóstico sin filtrado; compartir si se desea solamente las líneas `S01 R01` de recuentos (no dumps ni logs completos). Si algo falla, no repetir automáticamente: inspeccionar el motivo.

## 5. Contraste con PayPal — pendiente de autorización específica de lectura

**Nunca comparar únicamente contra la BD**. Un cobro puede haberse confirmado externamente y perdido su ACK local; órdenes, autorizaciones, capturas, reembolsos, contracargos y disputes pueden no figurar en la copia. La prueba de ausencia es más exigente que la prueba de presencia.

Antes de cualquier acción externa, el propietario debe definir:

- **Cuenta(s) merchant** y **entorno** correcto (Sandbox vs Live), intervalo completo desde primer uso del botón PayPal hasta el momento UTC de desactivación efectiva y desde entonces hasta el corte actual, incluyendo zonas horarias y zona de liquidación.
- Fuente **autoritativa del proveedor**, obtenida con acceso de solo lectura autorizado: órdenes, capturas, reembolsos, disputas y movimientos de saldo por periodo y divisa; estado de webhooks fallidos/no entregados y entregas pendientes; confirmación de si existieron operaciones desde fecha del backup.
- Ficha de reconciliación **privada y local por operación**, solo para el revisor financiero autorizado, con referencias efectivas del proveedor, estado, monto, divisa, fecha, eventos/respuestas y clasificación. Nunca publicar los IDs al repositorio ni al chat.
- Acta **agregada**: número de operaciones por clase y entorno, totales monetarios de proveedor previamente validados por contabilidad, coincidencias, discrepancias, importe pendiente de investigación, fechas del corte, evidencia de quién revisó y acciones seguras propuestas. Si los montos totales se consideran confidenciales, conservarlos solo en acta privada y compartir únicamente la clasificación PASS/NO-GO.
- Tratar cada discrepancia como **QUARANTINE** hasta evidencia concluyente. No borrar IDs históricos, no crear ni capturar de nuevo órdenes, no invalidar presupuestos y no cerrar una incertidumbre basándose solo en el silencio de un webhook.
- **Si hay cero referencias en el backup, G05 sigue ABIERTO** hasta revisar datos actuales y libro del proveedor: el backup puede ser anterior a una orden, una solicitud puede haberse borrado o el ACK haberse perdido antes de guardar el ID.

### Criterio de cierre del gate G05

**PASS** solo con inventario actual completo (no exclusivamente copia del 10/10), intervalo y cuentas identificados, contraste PayPal Live/Sandbox basado en evidencia, cero discrepancias no resueltas o retenciones explícitas que imposibiliten nuevos cobros en esos expedientes, evidencia de refunds/disputes, responsable financiero revisor y acta fechada. Cualquier duda sin evidencias mantiene **NO-GO**.

Un resultado `S01 R01 PASS LOCAL` significa **solo ejecución correcta del inventario de una copia**, nunca ausencia de cobros y nunca autorización de Stripe. El bloqueo financiero y la prohibición de fusionar/desplegar continúan.

## 6. Restricciones

No consultar hoy Railway, PayPal Live/Sandbox, Stripe o MERU. No migrar, reactivar PayPal, hacer órdenes, capturas, reembolsos o transferencias, ni cambiar variables, webhooks, PR anteriores o `main`. El esquema de U04 #29 sigue sin integrarse. La facturación fiscal corresponde a Rafa fuera de la aplicación.
