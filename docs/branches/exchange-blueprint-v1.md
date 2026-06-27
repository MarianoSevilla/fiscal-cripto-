# Exchange Blueprint v1 — Documento de referencia de rama

## Datos de partida

| Campo           | Valor                                                     |
|-----------------|-----------------------------------------------------------|
| Commit inicial  | `b812675700ded2912bb630d5b51c7c4bad45df93`                |
| Mensaje commit  | feat(bitget): support multi-file spot trading history     |
| Rama base       | `feat/bitget-multiarchivo-spot-trading`                   |
| Rama de trabajo | `feature/exchange-blueprint-v1`                           |
| Tag de seguridad| `pre-exchange-blueprint`                                  |
| Fecha de inicio | 2026-06-26                                                |

## Objetivo de la rama

Rediseño del flujo de trabajo de la herramienta de exchanges para eliminar callejones sin salida tras la generación de un informe FIFO.

Al finalizar el sprint, cualquier exchange del sistema dispondrá de las siguientes acciones post-informe:

1. Generar el informe de otro ejercicio fiscal utilizando el mismo CSV, sin re-subir.
2. Analizar otro exchange (navegación directa a `/[exchange]`).
3. Comenzar un nuevo análisis del mismo exchange con otro CSV.

Este patrón se denominará **Exchange Blueprint** y pasará a ser el estándar para cualquier exchange incorporado al sistema.

## Alcance declarado del sprint

- Mejora de experiencia de usuario. No modifica el parser, el motor FIFO ni la lógica fiscal.
- Cambios esperados: `templates/tool.html`, `fiscal_app_export/app.py` (capa de orquestación y rutas).
- Módulos excluidos por gobierno: `motor_fifo.py`, `clasificador_*.py`, `generador_xml_721.py`, `custodios_721.py`, `precios_historicos.py`.

## Cómo volver al estado anterior

```bash
# Volver al estado exacto del tag (sin pérdida de datos):
git checkout pre-exchange-blueprint

# O restaurar la rama base de la que partió este trabajo:
git checkout feat/bitget-multiarchivo-spot-trading
```

El tag `pre-exchange-blueprint` apunta permanentemente al commit `b812675` y no se puede mover accidentalmente.

## Estado de ficheros no rastreados al inicio de la rama

Los siguientes ficheros estaban presentes en el directorio de trabajo pero no forman parte del histórico git en este punto de partida. No se incluyen en el tag ni en la rama:

- `CLAUDE.md`
- `docs/` (salvo este documento)
- `ARQUITECTURA-SILO-HERRAMIENTAS-2026-06-16.md`
- `AUDITORIA-NUCLEO-2026-06-11.md`
- `ESTRATEGIA-SILO-HERRAMIENTAS-2026-06-16.md`
- `PLAN-IMPLEMENTACION-SILO-HERRAMIENTAS-V1-2026-06-16.md`
- `SPRINT1-SILO-HERRAMIENTAS-RUNBOOK.md`
- `SPRINT1-SILO-HERRAMIENTAS-SPEC-2026-06-16.md`
- `skills/`
- `ejemplo_detalle-ventas-y-permutas.png`
- `ejemplo_resumen-fiscal-renta.png`
- `ejemplo_ventas_permutas.pdf`
