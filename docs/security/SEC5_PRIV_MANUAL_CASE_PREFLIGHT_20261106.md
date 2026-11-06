# SEC5-PRIV — Preflight manual por expediente, sin actuaciones sobre datos

**Fecha:** 06/11/2026. **Estado:** especificación y prueba sintética de una barrera de decisión; **sin fusión ni despliegue** mientras esta PR esté en revisión. **No autoriza** una supresión, un bloqueo ni un cambio de permisos, aunque todas las casillas indiquen «revisado».

## Conclusión y uso permitido

Con las evidencias actuales no puede certificarse una supresión integral de una persona ni el **bloqueo legal** previsto en el art. 32 LOPDGDD. Los pilotos de aislamiento, recuperación y supresión se han comprobado en CI con datos sintéticos. No existe todavía un almacén productivo de bloqueo, un registro externo duradero de decisiones que permita conciliar **backups** antiguos ni una política jurídica definitiva por expediente.

Para gestionar una solicitud real, el operador sigue el procedimiento vigente `SEC5_PRIV_DERECHOS_SUPRESION_PROCEDIMIENTO.md`. Antes de cualquier acción irreversible, debe superar **seis puertas**, tal como exige el contrato `SEC5_PRIV_CASE_REVIEW_CONTRACT_20261102.json`:

1. **IDENTITY_AND_SCOPE:** identidad verificada por medios proporcionados; examinar vínculos por ID y los posibles correos copiados antes de desactivar o sobrescribir el email. Una coincidencia de correo **no prueba titularidad**.
2. **PURPOSE_AND_LEGAL_BASIS:** finalidad, responsable, base, fecha inicial real, excepciones y revisión justificadas en las **17 tablas ORM** que corresponda. Los hitos de 24 meses y 30/90/180 días **no autorizan eliminación automática**.
3. **FINANCIAL_AND_EXTERNAL_DEPENDENCIES:** distinguir soporte abierto, servicios pendientes, **pagos** y su idempotencia, devoluciones/disputas y derechos futuros; contrastar las actuaciones posibles en **Stripe**, **Gmail**, **Resend**, Railway y con **Rafael** como custodio profesional según el reparto efectivo de responsabilidades. Las comprobaciones externas no se presumen.
4. **SQL_AND_HTTP_ISOLATION:** si se propone reservar datos, demostrar aislamiento efectivo frente a login ordinario, API, panel, descargas, exportaciones y procesos; no basta desactivar la cuenta o marcarla como archivada. Las pruebas actuales son de laboratorio.
5. **ATOMICITY_AND_BACKUP_RECONCILIATION:** plan de reversión e idempotencia, backup reciente restaurable y registro externo de decisiones posteriores a la copia, con conciliación antes de abrir tráfico. Un `pg_restore` correcto no demuestra ausencia de reexposición.
6. **EXPLICIT_PRODUCTION_AUTHORIZATION:** revisión humana competente, propuesta limitada a los datos/campos afectados, comprobaciones de seguridad, aprobación explícita y ventana de intervención identificada. La aprobación de este documento **no** cubre producción.

## Resultado del preflight sintético

El módulo `fiscal_app_export/tests/privacy_case_preflight.py` es **solo para pruebas**, no una herramienta de ejecución ni una comprobación que contacte sistemas reales. No admite datos de clientes: el paquete ficticio tiene exclusivamente `outcome` y un mapa de seis declaraciones. Cada declaración es `PENDING`, `DECLARED_REVIEWED` o `CONFLICT`.

- **NO_GO_CONFLICT:** alguna declaración es contradictoria; conservar evidencias y resolver el conflicto antes de seguir.
- **NO_GO_INCOMPLETE:** falta al menos una puerta; recopilar y verificar evidencias antes de revisar una posible actuación.
- **NO_GO_DESTRUCTIVE_ACTION:** se propuso `MANTENER_OPERATIVO` o `REVISION_ESPECIAL`; no hay propuesta válida de actuación destructiva.
- **HUMAN_REVIEW_REQUIRED:** se declararon revisadas las seis puertas para una propuesta `SUPRIMIR` o `BLOQUEAR_ART32`. **No significa que las evidencias sean reales, suficientes, auténticas o aprobadas.** Solo permite elevar un expediente a revisión humana independiente.

Todas las respuestas contienen `allow_erasure=false`, `allow_legal_blocking=false`, `allow_sql_writes=false`, `allow_deployment=false`, `evidence_independently_verified=false` y `real_case_handling_supported=false`. Ni siquiera una cadena de seis `DECLARED_REVIEWED` autoriza cambios. El test rechaza claves inesperadas (por ejemplo, correo, nombre o `user_id`), permisos automáticos, campos incompletos y el cambio del contrato original a `execution_enabled=true`.

## Qué se hace hoy al recibir una solicitud

El titular registra la fecha de recepción en un canal restringido, verifica identidad proporcionalmente, recorre finalidad y fuentes, conserva el rastro mínimo necesario y responde dentro de los plazos previstos en el RGPD. Ante un vacío de evidencia, el caso se deja en **revisión especial** con motivo y responsable. Si existe obligación o controversia que impida la supresión, se documenta la excepción concreta y la modalidad de acceso adecuada; no se promete que exista bloqueo operativo en la plataforma.

Una cuenta sin relaciones conocidas en el inventario sintético no equivale a un caso real sin datos personales. Debe contrastarse el tratamiento fuera de PostgreSQL (documentos temporales, logs, correos, proveedores, soportes de tercero) y el posible texto libre no identificado por FK. Una baja `POST /api/delete-account` solo desactiva/desidentifica la cuenta; **no implementa supresión completa** de registros del servicio.

**No guardar datos personales, documentos, contraseñas, capturas con PII ni identificadores reales** en un paquete de prueba, GitHub Actions, GitHub Issues o el chat. No ejecutar este módulo contra production, ni transformar su resultado en una orden SQL.

## Verificación y límites de esta entrega

Pruebas parametrizadas para las ocho situaciones adversariales del contrato (email compartido, cuenta ya desactivada, S01, límite SQL, fallo transaccional, backup anterior, proveedor externo y revisión por inactividad), todos los estados y las seis puertas. Se rechazan contratos manipulados, payloads extra e inputs no válidos; no se tocan conexiones, APIs, Flask, PostgreSQL o proveedores. Se exige CI **backend-tests**, **postgres-bootstrap** y **browser-navigation** sobre HEAD exacto y revisión adversarial del diff.

**No se crean** una ruta pública, un endpoint de administrador, una interfaz de aprobación, un cron, un journal de producción ni una solución de conservación; el módulo queda aislado bajo `tests/`. Las decisiones legales, la firma del acuerdo con Rafael, las responsabilidades sobre cobro/facturación y el mecanismo real de bloqueo/restauración siguen fuera del alcance de esta entrega.

**Puerta final:** sin fusión ni despliegue ni tratamiento real de datos hasta autorización específica. El contrato `DESIGN_ONLY` continúa vigente y SEC5-PRIV global permanece abierto.
