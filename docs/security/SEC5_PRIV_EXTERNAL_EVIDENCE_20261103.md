# SEC5-PRIV — Evidencia externa a la copia y preapertura: contrato de laboratorio

**Corte:** 03/11/2026. **Estado:** CI sintética; no autorizada para producción.

## Decisión de alcance

La restauración sintética de la PR #182 probó integridad de filas, transacción e idempotencia, pero mantenía el manifiesto en la memoria del proceso. Esta iteración demuestra **persistencia local real fuera de PostgreSQL** y comprobación contra una huella de referencia suministrada **independientemente**. Se reutiliza el mismo ensayo `qa_sec5_priv_restore_pg18.py`; no se crea un motor general ni se toca el arranque productivo.

El módulo `sec5_priv_recovery_evidence.py` expone solo dos operaciones sin efectos colaterales al importarlo:
- `persist_immutable(ruta, manifiesto)`: guarda un JSON canónico mediante creación exclusiva (no sobrescribe), permisos restrictivos, `fsync` del fichero y directorio; devuelve SHA-256 del contenido para que el operador lo custodie fuera de esa ubicación.
- `read_pinned(ruta, trusted_head=...)`: falla si falta la referencia confiable, el fichero, la integridad, la forma canónica, permisos restrictivos o si se utiliza un enlace simbólico. **Una huella incorporada dentro del propio archivo no sería prueba de autenticidad.**

## Prueba de recuperación

1. En la CI se crea PostgreSQL 18 desechable con las **17 tablas ORM** y datos ficticios. Se obtiene un `pg_dump` real anterior a dos decisiones de privacidad simuladas.
2. Se firma el manifiesto sintético y se escribe de forma inmutable en un directorio temporal **fuera de la base/copia**. Se conserva la huella esperada en una variable distinta al fichero (simulación de una referencia custodiada por el operador).
3. El laboratorio rechaza falta de fichero, huella incorrecta o antigua, cambios en los bytes del fichero y tentativa de sobreescritura.
4. Destruye y recrea únicamente la base de CI y ejecuta `pg_restore`. Lee el manifiesto desde disco contra la huella independiente. Antes de reconciliar, la comprobación de preapertura **rechaza** la base recuperada.
5. Reaplica las decisiones sintéticas tras verificar huellas **HMAC de la fila completa**, sujeto correcto y copia exacta. El fallo parcial revierte todo; la operación correcta queda idempotente y el usuario ajeno conserva sus datos. El rol SQL ordinario no puede leer el contenido reservado.

## Límites reales y NO-GO

- **Un directorio temporal de CI no constituye un almacén duradero de producción.** Railway tiene volumen PostgreSQL, pero la configuración actual del servicio web no incorpora un volumen ni bucket independiente. Nunca guardar el registro exclusivamente en ese volumen de PostgreSQL, en el contenedor web efímero o en el propio backup.
- Una referencia SHA-256 demuestra igualdad frente a una huella **ya confiable**, pero no demuestra que sea la **última**. HMAC protege la autenticidad del manifiesto recibido, no prueba la completitud ni actualidad de las decisiones. El operador necesita un índice externo autenticado, monotónico y protegido frente a reversión; ausencia de cualquier evento exige NO-GO.
- Los identificadores del manifiesto están seudonimizados, no necesariamente anonimizados. No incluir registros reales en repositorios GitHub, artefactos de CI o logs. Custodiar los secretos y trazas conforme a su finalidad.
- El ensayo **no está conectado al arranque** `startup_schema_gate.py`, `Procfile`, Flask ni Railway. Actualmente una restauración real **no queda bloqueada automáticamente** por este módulo. Debe permanecer desconectada de tráfico por controles operativos previos a la apertura. No presentar este ensayo como barrera productiva.
- No habilita supresión ni bloqueo legales efectivos, ni actúa sobre cuentas reales, asesoramiento, Stripe, Gmail, Resend, archivos externos o copias manuales existentes. Las **copias antiguas** carecen de un historial externo que pueda reconstruirse con certeza por este ensayo; requieren inventario y revisión específica.
- Habilitar un almacén externo real, custodiar claves, crear un índice confiable y conectar una barrera de reapertura implicaría **cambios de producción** y permisos/configuración de recuperación que requerirán diseño, pruebas y autorización específica antes de desplegar.

## Criterio de aceptación

PR limitada a biblioteca de evidencia, nuevas pruebas, ampliación del ensayo PostgreSQL 18 existente y este documento. CI obligatoria **3/3 SUCCESS** para el HEAD exacto. Sin migraciones, rutas, procesamiento fiscal, `Procfile`, `startup_schema_gate.py` ni variables Railway.
