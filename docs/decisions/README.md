# Sistema de ADRs — Architecture Decision Records

## Propósito

Este directorio registra las decisiones arquitectónicas del proyecto: qué se decidió,
por qué se decidió así, y qué alternativas se descartaron. Su función no es documentar
el estado actual del sistema — eso es `ARCHITECTURE.md`. Su función es responder la
pregunta que `ARCHITECTURE.md` no responde: *¿por qué el sistema es así y no de otra
manera?*

El destinatario principal es quien está a punto de cuestionar o cambiar una decisión
existente — humano o AI — y necesita saber qué razonamiento llevó a la situación
actual antes de proponer algo diferente.

---

## Cuándo crear un ADR

Un ADR es necesario cuando la decisión cumple las tres condiciones simultáneamente:

1. **No es obvia desde el código**: alguien puede ver QUÉ se decidió leyendo el código,
   pero no POR QUÉ.
2. **Revertirla tiene coste arquitectónico**: si se cambia, otras partes del sistema
   también deben cambiar.
3. **Había alternativas viables**: se eligió A en lugar de B, y B era una opción
   razonable.

**También se crea un ADR cuando:**
- Se va a incorporar una fuente de datos nueva y hay que documentar el patrón
  arquitectónico elegido (ver `ENGINEERING_PRINCIPLES.md` §9).
- Se resuelve permanentemente un vector de seguridad activo
  (`ENGINEERING_PRINCIPLES.md` §6).
- Se propone un cambio a un principio de `ENGINEERING_PRINCIPLES.md` — el ADR se crea
  primero, el documento se actualiza después, si procede (§17).
- Una decisión requirió validación del asesor fiscal o del responsable de producto: el
  ADR es el registro de que ese gobierno fue ejercido.
- Una discrepancia documentada en `ARCHITECTURE.md` (como la de nomenclatura VÁLIDO/LISTO)
  se resuelve mediante decisión formal.

---

## Cuándo NO crear un ADR

- **Convenios de ingeniería**: pertenecen a `ENGINEERING_PRINCIPLES.md`.
- **Criterios fiscales**: son autoridad del asesor fiscal colegiado. Si se documentan,
  en un documento de criterios fiscales específico.
- **Decisiones de producto**: pertenecen a `PROJECT_IDENTITY.md` o al proceso de
  gobierno.
- **Versiones de dependencias**: hechos técnicos de `ARCHITECTURE.md` §3.
- **Decisiones completamente reversibles**: si se puede deshacer mañana sin impacto
  arquitectónico, no necesita registro.
- **Decisiones obvias desde los documentos fundacionales**: si el porqué se puede
  deducir directamente de `PROJECT_IDENTITY.md` o `ENGINEERING_PRINCIPLES.md`, no hay
  información que añadir.

**Regla práctica:** si alguien que ha leído el código y los cuatro documentos
fundacionales podría llegar a la misma decisión por razonamiento propio, no hace falta
un ADR. Si no podría — porque faltaría contexto, o porque la decisión depende de una
restricción no visible — el ADR es necesario.

---

## Plantilla

```markdown
# ADR-NNNN — [Decisión adoptada, enunciada directamente]

**Estado:** Aceptado | Sustituido por [ADR-NNNN](enlace) | Obsoleto
**Fecha:** YYYY-MM-DD

## Contexto

[El problema o situación que hizo necesaria esta decisión. Qué fuerzas estaban en
juego, qué restricciones existían. 3-6 líneas.]

## Decisión

[La decisión adoptada, enunciada directamente. "Decidimos X." Si es una decisión
reconstruida del código, indicarlo: "La decisión se infiere del código; no se conocen
las alternativas originalmente consideradas."]

## Alternativas consideradas

[Las opciones que se descartaron y por qué. Si las alternativas son desconocidas
porque la decisión es reconstruida, decirlo explícitamente.]

## Consecuencias

[Qué se hace más fácil, qué se hace más difícil, qué deuda introduce esta decisión.
Honestidad sobre los costes, no solo sobre los beneficios.]

## Gobernanza [solo si aplica]

[Si la decisión requirió validación del asesor fiscal o del responsable de producto:
qué se validó, cuándo, y cómo queda trazado.]
```

**Qué no incluye el template:**
- Autor: está en el historial de git.
- Notas de implementación: pertenecen al código.
- Fecha de revisión: los ADRs no se revisan, se sustituyen.

---

## Estados

**Aceptado** — la decisión está vigente y la arquitectura la refleja.

**Sustituido** — una decisión posterior cambió esta. El ADR queda marcado con
referencia al que lo sustituye; el nuevo ADR referencia al sustituido. La cadena
completa es la historia de cómo evolucionó esa decisión.

**Obsoleto** — la decisión ya no aplica y no fue sustituida por una nueva.

No existe estado "Propuesto": si una decisión no está lista para adoptarse, no es un
ADR todavía.

---

## Regla de inmutabilidad

Un ADR aceptado nunca se edita. Si hay que corregir o cambiar algo, se crea un nuevo
ADR que sustituye al anterior. Esta regla garantiza que la cadena de razonamiento sea
completa e inviolable — especialmente importante en un sistema con gobernanza fiscal,
donde saber qué se decidió en qué momento puede tener consecuencias reales.

---

## Relación con ARCHITECTURE.md §18

`ARCHITECTURE.md` §18 contiene el resumen ejecutivo de decisiones arquitectónicas
vigentes: una tabla de una línea por decisión, orientada a quien lee la arquitectura
para entender el sistema.

Este directorio contiene el detalle completo: contexto, alternativas, consecuencias.

Las dos piezas son complementarias y sirven a lectores distintos. Cuando existe un ADR
para una entrada de §18, esa entrada enlaza al ADR. §18 nunca queda vacío: es el
índice permanente de decisiones vigentes; `docs/decisions/` es el registro histórico
completo.

---

## Índice de ADRs

| ADR | Título | Estado | Fecha |
|-----|--------|--------|-------|
| [ADR-0001](ADR-0001-monolito-flask.md) | Un único proceso Flask en lugar de microservicios | Aceptado | 2026-06-25 |
| [ADR-0002](ADR-0002-exchange-template-standalone.md) | Plantillas HTML standalone por exchange como nuevo estándar | Aceptado | 2026-06-28 |
