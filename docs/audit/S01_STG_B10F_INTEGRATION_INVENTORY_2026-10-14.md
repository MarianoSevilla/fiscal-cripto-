# STG-B10F — Inventario de integración S01 y control de cambios

**Fecha de corte:** 14/10/2026. **Tipo:** auditoría exclusivamente documental / lectura GitHub. No se han fusionado ni desplegado PR; no cambia aplicación, pagos, entornos ni DB.

## Estado reproducible

- `main`: **`56882073295faae3bd1bc3632288a970acb330da`**, protegido y sin cambios durante STG-B09 → B10E.
- Consulta GitHub de PRs abiertas: **40 PR DRAFT (numeradas #29–#68)** en el momento del inventario. El número cambia con posteriores PR o cierres y no es prueba de integrabilidad.
- Comparación GitHub **`main...security/s01-stg-b10e-full-regression`**: **107 commits por delante, 0 por detrás y 105 archivos distintos**. Se trata de la suma acumulada de múltiples fases, no únicamente del laboratorio.
- Cadena B10 de PRs (todas abiertas y DRAFT): **#60 → #61 → #62 → #63 → #64 → #65 → #66 → #67 → #68**. Cada rama apunta exactamente a su PR base, comprobado por metadatos; las comparaciones #60→#67 mostraron `ahead` y `behind=0`. Estos resultados no sustituyen revisión manual o suite global.
- Las pruebas especializadas **B10D #38478432071** aprobaron dos escenarios sintéticos PostgreSQL 18 (fallo y saludable). **B10E #38535746502** ejecuta el conjunto completo de tres trabajos (Python, PostgreSQL18 y Chromium); su resultado final debe comprobarse antes de recomendar integración.
- Railway S01 LAB: Postgres `f680f3fc-4581-44ff-8bc1-d034840f2c7e`; web `212f4f52-b349-4387-a046-9f6b08237d2e` y maintenance `9728d19b-7d17-4acb-8be1-c4b0847179df` sin fuente y sin despliegue. No se ha corrido DDL real en esta secuencia.

## Mapa de dependencias de alto nivel

```text
main (56882073...)
├─ PR #29 [U04] PayPal antiguo — rama propia
├─ PR #30 U04 PREFREEZE — rama propia
├─ PR #31 STG-LOCK — rama propia
├─ PR #32 firma Stripe — rama propia
├─ PR #33-40 S01 test — ramas propias / integración diversa
├─ PR #41 Retirada PayPal + Alembic
│  ├─ PR #42 auditoría preintegración [lateral]
│  └─ PR #43 corrección AUD-001/003
│     └─ #44 → #45
│        ├─ #47 → #48 [auditoría PayPal lateral]
│        └─ #49 → #50 → #51 → #52 → #53
│           ├─ #54 [diseño Connect lateral]
│           └─ #56 → #57 → #58 → #59 → #60
│              → #61 → #62 → #63 → #64 → #65
│              → #66 → #67 → #68
├─ PR #46 auditoría financiera [rama propia]
└─ PR #55 auditoría negocio [rama propia]
```

**Nota:** el dibujo expresa **bases de PR configuradas en GitHub**, no identifica qué commits fueron reutilizados, cherry-pickeados o subsumidos; eso requiere revisión de parches. `#33-#40` designa bases `main`, no obliga a considerarlas una sola unidad ni se debe fusionarlas en masa.

## Riesgos de consolidación pendientes (NO-GO merge)

1. **Desarrollo paralelo:** #29 (conciliación PayPal) y #41 (retirada de PayPal) responden a políticas potencialmente distintas. Comprobar cuál prevalece antes de incorporar código de pagos; no trasladar automáticamente #29.
2. **Paridad de defensas:** las PR #30 PREFREEZE, #31 staging y #32 firma Stripe parten de `main` mientras que la rama acumulada implementa parte de esos controles. Revisar cobertura por cambio y evitar fusiones duplicadas o regresiones.
3. **Bifurcación fiscal/negocio:** PR #54 diseña Connect y no integra directamente la cadena que continúa por #56. Mantenerla fuera hasta resolver la política de facturación/comisiones.
4. **Ramas de auditoría:** #42, #46, #47, #48 y #55 son paralelas o acumuladas fuera de la rama principal; clasificar evidencia/documentación y diferencias de código antes de decidir destino.
5. **Superficie de cambio:** 107 commits / 105 archivos implica que una eventual integración `main` afectará código financiero, rutas Flask, modelos, migraciones, plantillas, CI y tests. No equivale a un merge solo del laboratorio.
6. **Riesgo económico:** preservar suspensión PayPal/Stripe, deshabilitación de escrituras financieras y verificación criptográfica de webhooks; no habilitar cobros por introducir las tablas.
7. **Base de datos:** ensayos contra PG18 sintético no prueban estructura ni backup restaurable de producción/staging. Despliegue web y DDL real exigen autorizaciones por separado.

## Orden recomendado, todavía NO autorizado para ejecución

- **I. Inventario de diferencias y redundancias**: comparar PR por PR desde el primer punto común; producir matriz de cambios funcionales, migraciones, dependencias y políticas de cobro, con revisión independiente.
- **II. Batería completa sobre rama acumulada**: exigir Python, PG18 y Chromium verde, seguridad financiera y pruebas de aislamiento sin conexión a proveedores.
- **III. Plan de integración *conservador***: seleccionar segmentos funcionales pequeños, verificar SHA exacto, ausencia de nuevas modificaciones y reversión no destructiva. Nunca aplicar automáticamente `merge/squash/rebase/cherry-pick` ni activación de auto-merge.
- **IV. Integración/despliegue futuros**: autorizaciones separadas por PR/grupo, staging, DDL, web, dinero y correo. Un CI PASS no es un GO financiero.
- **V. Rediseño UX/UI**: comenzar solo tras comprobar explícitamente la estabilidad del código y producción, sin trabajo pendiente que el rediseño pueda pisar.

### Detalle operativo para siguiente revisión

Antes de aprobar cualquier integración verificar:
`head_sha`, `base_sha`, `mergeable`, protecciones `main`, checks exactos, diferencias de ficheros, flujos financieros activables, invariantes DB/DDL y presencia de dependencias secundarias. En caso de discrepancia o incertidumbre: STOP, investigación solo lectura y nueva evaluación.

**Resultado de esta fase:** inventario disponible para revisión; **NO-GO** para fusiones a `main`, despliegues, migraciones reales o activación de pasarelas.
