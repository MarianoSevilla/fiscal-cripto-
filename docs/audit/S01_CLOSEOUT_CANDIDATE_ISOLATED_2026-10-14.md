# S01 — Candidato aislado de cierre técnico (sin desplegar)
Fecha: 2026-10-14. Preparación de una única rama desde PR #58 / `74bea12848aa53e05a653cec8802a7b675819da0`.

## Alcance deliberadamente limitado
- Port exacto del cortafuegos `staging_isolation.py` y `lab_isolation.py` comprobado en la cadena #89; en `app.py` el fragmento de integración es idéntico al de #89. Sin código de recuperación, restore, backup ni ejecutores DDL.
- El laboratorio REAL usa el servicio web `212f4f52-b349-4387-a046-9f6b08237d2e` y **exige** `postgres-im3h.railway.internal` (Postgres-Im3h, ID `317b21e9-b259-4b15-902a-a7bec69b7407`, clúster previamente verificado `7696517018472497211`). Rechaza `postgres.railway.internal` (original), el host staging, credenciales externas, URLs públicas y marcadores de Railway equivocados.
- La web de laboratorio solo permite **GET/HEAD /healthz**, rechaza el resto de API/FIFO/asesoría/pagos y bloquea correo. El CI funcional usa SQLite/PG18 sintético, jamás los datos de clientes.
- Staging actual conserva identidad y lista cerrada de rutas; producción solo se modifica tras integración y aprobación futura. `main` no cambia.
- El contrato comercial vigente excluye PayPal S01, envío de presupuestos y cobros hasta autorización aparte; se excluye PR #29 y el diseño 50/50 de #54. Sin claves/pagos Stripe/PayPal/MERU, correos ni facturación en esta fase.

## QA limitada al candidato
`.github/workflows/qa-s01-closeout-integration.yml` ejecuta tres jobs aislados: Python regresión con cortafuegos y bloqueo de red, PostgreSQL18 efímero (migraciones sintéticas de S01), Chromium/Flask con datos ficticios. Disparadores **solo** push a `security/s01-closeout-integration-lab-readonly` y PR contra la rama #58. Permisos GitHub de lectura; no deploy ni secretos de proveedor.

## Gates para uso futuro (NO AUTORIZADOS por este commit)
1. Exigir CI verde sobre el SHA exacto y revisar diff. Verificar que los guardrails no se desactivan en pruebas.
2. Antes de un deploy LAB, inspeccionar conexión `DATABASE_URL` del servicio web **sin exponer secretos** y cambiar su referencia al servicio **Postgres-Im3h** solo tras autorización. En inventario previo el web usaba el PostgreSQL original; este commit NO lo corrige en Railway.
3. Mantener LAB privado (0 dominios, 0 TCP proxies), identidad y cuenta de email/proveedor deshabilitadas; confirmar volumen original y recuperado independientes. No iniciar la web durante esta fase.
4. Aprobación independiente para despliegue de la web LAB y prueba /healthz, más otra aprobación para permitir cualquier endpoint que interactúe con DB o usuarios.
5. Producción: autorización **distinta** para backup/migración, merge, despliegue y recuperación; un PASS en este laboratorio no implica GO productivo.

Estado al crear: **SOLO CÓDIGO Y CI. Ningún cambio en Railway, main, pagos o correo.**
