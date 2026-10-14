# STG-B10E · Regresión completa antes de integrar — 14/10/2026

## Problema identificado

En la rama apilada del laboratorio, los workflows específicos de B10A–B10D han pasado, pero el workflow general `.github/workflows/required-ci.yml` está limitado a PRs y pushes de `main`. Por tanto, el conjunto de regresión de producto no se había lanzado necesariamente sobre el árbol combinado B10D.

## Solución sin cambios de producción

Se añade un workflow de **solo QA** denominado `qa-s01-stg-b10e-full-regression.yml`, basado en `required-ci.yml` del SHA `23c0a9e9f87e9ac637323c9c5951e04458fb106a`. Solo responde a PRs cuya base es `security/s01-stg-b10d-adversarial-recovery`, con permisos `contents: read`, sin secrets y sin `deploy`.

Se ejecutan los tres jobs heredados:

1. **backend-tests:** integridad de pins, suite completa Python/pytest (raíz + aplicación), firewall real Flask para staging/lab sin proveedores.
2. **postgres-bootstrap:** PostgreSQL 18 efímero; bootstrap defensivo, prefreeze, concurrencia Stripe sintética, carreras de reserva, historial PayPal, seis casos Alembic, recuperación G04, C2.
3. **browser-navigation:** Chromium local/Playwright, navegación responsive y Flasks sintéticos, flujos suspendidos de asesoramiento, evidencia de screenshots no sensibles con retención de 7 días.

**Importante:** la CI se basa en el proyecto GitHub y ejecuta su código no fusionado contra fixtures de GitHub, no contra la red de Railway. El código de producción, sus Procfiles, migraciones, identidades, fuentes, variables y bases de datos no se modifican.

## Aceptación y límites

- Deben aprobar **los tres jobs** y los checks específicos B10D previos. Un único error = NO-GO.
- PR en borrador apilada sobre PR #67. No merge ni auto-merge.
- Aunque pase, no demuestra DSN efectivo de Railway, restauración desde backup o safety de un futuro ejecutor real.
- Sin autorización independiente: **NO-GO** para DDL en Railway y despliegues de web o maintenance.
