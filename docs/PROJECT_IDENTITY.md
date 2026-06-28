# PROJECT_IDENTITY.md
### La constitución del proyecto — no su fotografía

## 0. Vigencia
- Creado: 2026-06-25. Última revisión: 2026-06-25.
- No se revisa por calendario. Se revisa cuando cambie la misión del
  apartado 2, el gobierno del apartado 5, o la composición del ecosistema
  del apartado 3. Ningún otro cambio (stack, proveedor, framework,
  arquitectura interna) debería obligar a tocar una palabra de este
  documento. Si lo hace, algo que pertenece a `ARCHITECTURE.md` o a
  `ENGINEERING_PRINCIPLES.md` se ha colado aquí.

---

## 1. Principios fundacionales

No cambian aunque cambien el stack, el proveedor, el equipo o la
arquitectura. Si una decisión futura los contradice, la decisión está
equivocada, no este apartado.

1. La exactitud del cálculo fiscal es no negociable. Prevalece siempre
   sobre velocidad de entrega, crecimiento, conversión o cualquier otra
   prioridad de producto.
2. Ninguna aproximación o simplificación de cálculo fiscal se introduce,
   mantiene o elimina sin validación expresa del asesor fiscal colegiado —
   corregir un cálculo también es una decisión sobre el resultado fiscal
   del usuario, no solo una decisión técnica.
3. El usuario nunca presenta un resultado cuyas limitaciones conocidas no
   le han sido comunicadas explícitamente; una aproximación documentada
   solo en el código no cuenta como comunicada.
4. La confianza del usuario en la exactitud del resultado es el activo más
   valioso del proyecto. Cualquier decisión que la arriesgue para ganar
   tráfico, velocidad o conversión es incorrecta por defecto.
5. Cualquier producto, línea o funcionalidad se incorpora solo si resuelve
   un problema real de cumplimiento fiscal cripto del usuario español —
   nunca porque sea técnicamente posible, esté de moda, o lo haga un
   competidor.
6. La autoridad sobre criterio fiscal y la autoridad sobre negocio/producto
   están separadas de forma permanente — no se fusionan en una sola
   persona, un solo rol, ni en ningún agente automatizado, presente o
   futuro, por capaz que sea.
7. El sistema debe ser siempre auditable y explicable: cualquier resultado
   fiscal debe poder justificarse, operación por operación, ante el
   usuario, el asesor fiscal o la Agencia Tributaria. Un cálculo que no se
   puede explicar no se considera fiable, aunque sea correcto.
8. La identidad pública del proyecto se construye sobre rigor y
   transparencia, nunca sobre promesas o expectativas que no pueda
   sostener — ni presentación garantizada ante la AEAT, ni rentabilidad
   fiscal, ni resolución completa de la situación del usuario sin advertir
   sus límites.

---

## 2. Propósito

La misión de este proyecto no es vender asesoramiento fiscal ni vender
software por suscripción. La misión es convertirse en la plataforma de
referencia en España para resolver el cumplimiento fiscal relacionado con
criptomonedas.

Esto existe porque declarar operaciones con criptomonedas en España es
estructuralmente complejo (método FIFO, art. 37.2 LIRPF, Modelo 721 ante la
AEAT) y el coste de un error no es una mala experiencia de usuario — es una
declaración incorrecta ante la Agencia Tributaria. No existe hoy una
plataforma de referencia que resuelva esto de forma integral en español.

Ninguna decisión se justifica por el ingreso que genera si no acerca al
usuario a resolver su cumplimiento fiscal — ver principio fundacional 5.

---

## 3. El producto

Este proyecto no es un producto único: es un ecosistema de servicios
especializados, donde cada servicio resuelve un problema concreto del
usuario dentro de la misión del apartado 2, y conduce de forma natural al
siguiente cuando tiene sentido para el usuario — nunca de forma forzada.

**Estado actual del ecosistema** (vigente, no composición cerrada; el
detalle técnico de cada línea vive en `ARCHITECTURE.md`):

- Herramienta gratuita de generación de informes FIFO — puerta de entrada.
- Herramienta de Modelo 721.
- Contenido educativo (YouTube, web, recursos descargables).
- Asesoramiento fiscal humano especializado para casos complejos.

La condición para incorporar o retirar una línea es el principio
fundacional 5: valor frente a la misión, nunca modelo de monetización. No
se asume que el destino sea un SaaS de suscripción, ni que el asesoramiento
humano sea una fase temporal hacia otra cosa — ambas son hipótesis
abiertas, no decisiones tomadas.

---

## 4. Usuarios

- **Usuario autogestionado**: resuelve su FIFO o su Modelo 721 sin
  contacto humano. Puerta de entrada al ecosistema.
- **Cliente de asesoramiento fiscal humano**: casos complejos; relación
  puntual, no de suscripción.
- **Consumidor de contenido educativo**: puede no ser usuario registrado —
  parte superior del embudo hacia los dos anteriores.
- **Asesor fiscal colegiado**: no es un cliente. Es una autoridad del
  sistema — ver apartado 5.
- **Administración/operaciones internas** (rol `admin`): opera el negocio,
  no es destinatario de la misión.

Ninguna decisión de producto se optimiza para un segmento a costa de otro
sin pasar por el apartado 5 si toca criterio fiscal, o por el apartado 7 si
es un conflicto de prioridad de negocio.

---

## 5. Gobierno

**El responsable de producto — hoy Mariano Sevilla — tiene autoridad final
sobre:** visión y estrategia, modelo de negocio, experiencia de usuario,
arquitectura funcional, prioridades del roadmap, contenido educativo,
aceptación o rechazo de nuevas funcionalidades.

**El asesor fiscal colegiado tiene autoridad delegada y exclusiva sobre:**
interpretación normativa, criterios fiscales aplicados por el sistema,
cumplimiento con la legislación vigente, validación de cualquier
aproximación fiscal, y cualquier decisión que pueda alterar el resultado
fiscal mostrado al usuario.

**Ningún desarrollador, ni Claude, ni ningún asistente de IA presente o
futuro, tiene nunca autoridad para introducir o modificar un criterio
fiscal por iniciativa propia.** Puede detectar inconsistencias, proponer
alternativas, identificar riesgos y solicitar una decisión. Nunca decidir
unilateralmente sobre algo reservado a cualquiera de las dos autoridades.

**Cuando una decisión afecta simultáneamente al negocio y al criterio
fiscal, ambas autoridades deben intervenir antes de su implementación.**
Ninguna decisión de ese tipo se considera completa con una sola firma.

> Consecuencia no obvia: una corrección de bug que cambia el resultado
> fiscal calculado es, por definición, una decisión que altera el
> resultado fiscal del usuario — requiere validación del asesor fiscal
> antes de desplegarse, no solo revisión técnica, aunque se presente como
> "solo un fix".

> Nota de ubicación: el procedimiento operativo para solicitar y registrar
> esta validación pertenece a `ENGINEERING_PRINCIPLES.md`, no a este
> documento.

---

## 6. Marco regulatorio

El marco vigente hoy es el cumplimiento fiscal cripto en España: IRPF,
método FIFO según art. 37.2 LIRPF, y la declaración informativa Modelo 721
ante la AEAT.

Esto no es contexto de fondo: es la variable que reordena la severidad de
cualquier incidencia. Un error de cálculo fiscal tiene consecuencias
legales reales para el usuario. Por esa razón, ningún bug de cálculo se
trata nunca con la misma prioridad que un bug de presentación visual, sin
excepción.

Si la misión se extiende en el futuro más allá de España o del IRPF
cripto, este apartado debe revisarse explícitamente — ver apartado 0.

---

## 7. Prioridades

Orden de desempate para conflictos de roadmap. No sustituye al apartado 1;
lo aplica al día a día:

1. Corrección fiscal y cumplimiento normativo.
2. Confianza y transparencia con el usuario.
3. Coherencia con la misión.
4. Valor percibido por el usuario en cada línea del ecosistema, no ingreso
   inmediato.
5. Crecimiento y alcance — válido solo si no compromete lo anterior.
6. Velocidad de entrega o eficiencia de ingeniería — último criterio,
   nunca el primero.

---

## 8. Calidad

Jerarquía de severidad, válida para cualquier línea del ecosistema:

1. Pérdida o alteración silenciosa del resultado fiscal del usuario —
   severidad máxima siempre.
2. Indisponibilidad del servicio o pérdida de datos del usuario.
3. Comunicación insuficiente de una limitación o aproximación fiscal
   conocida.
4. Errores de experiencia de usuario que no afectan al resultado fiscal.
5. Deuda técnica y deuda de estilo.

Un bug de categoría 1 nunca se reprioriza por debajo de uno de categoría 2,
3, 4 o 5, sea cual sea su esfuerzo de corrección.

---

## 9. Evolución

- Cualquier nueva línea se evalúa por si resuelve un problema real de
  cumplimiento fiscal cripto del usuario español — principio fundacional 5
  aplicado al roadmap.
- El ecosistema puede crecer en líneas de producto, pero nunca a costa de
  diluir la separación de autoridad del apartado 5.
- La complejidad técnica nueva se introduce solo cuando una línea existente
  o nueva lo justifica por valor entregado al usuario, nunca por
  anticipación especulativa de escala futura.
- Ante tensión entre velocidad de lanzamiento y solidez del criterio
  fiscal, el criterio fiscal nunca cede — la línea espera, no al revés.
- Una línea que deja de aportar valor al usuario es candidata a
  discontinuarse; el criterio es el valor entregado, no la rentabilidad. Si
  afecta a criterio fiscal ya comunicado, sigue el apartado 5.

---

## 10. Decisiones reservadas

Cubre ambas autoridades del apartado 5. Ningún desarrollador ni asistente
de IA toma estas decisiones por iniciativa propia, bajo ninguna
circunstancia:

- Introducir, modificar o eliminar cualquier aproximación fiscal — **asesor
  fiscal colegiado.**
- Cambiar el umbral o criterio de obligación de declarar el Modelo 721 —
  **asesor fiscal colegiado.**
- Cualquier corrección de bug que altere el resultado fiscal calculado —
  **validación del asesor fiscal antes de desplegarse** (ver apartado 5).
- Incorporar o discontinuar una línea del ecosistema — **responsable de
  producto**; conjunta con el asesor fiscal si toca criterio fiscal.
- Cambiar el modelo de monetización de una línea existente — **responsable
  de producto.**
- Decidir el patrón de integración técnica de algo nuevo, sin impacto en
  criterio fiscal o negocio, **no** está reservado — es autonomía técnica
  plena. La frontera no es "qué es difícil", es "qué puede alterar el
  resultado fiscal o el rumbo de negocio".

---

## 11. Qué no es

- No es, ni se asume que su destino sea, un SaaS de suscripciones cerrado
  con planes y límites contractuales. Hipótesis abierta, no descartada ni
  confirmada.
- No es un sustituto del criterio profesional de un asesor fiscal
  colegiado para casos complejos — es un complemento; la línea de
  asesoramiento humano del apartado 3 lo demuestra, no es retórica.
- No persigue crecimiento o monetización como fin en sí mismo, desconectado
  de la misión — ver principio fundacional 5.

> Nota de ubicación: si custodia activos, si usa APIs de exchange, si
> persiste transacciones — son hechos de arquitectura vigente, no de
> identidad. Pertenecen a `ARCHITECTURE.md`.

---

## 12. Vocabulario

Términos de dominio fiscal/negocio que cualquier decisión de identidad
necesita compartir. El vocabulario técnico de implementación vive en
`ARCHITECTURE.md`.

- **FIFO**: cálculo de ganancia/pérdida por orden de entrada, art. 37.2
  LIRPF.
- **Modelo 721**: declaración informativa ante la AEAT sobre saldos
  cripto custodiados en el extranjero.
- **Swap**: intercambio directo cripto-a-cripto, sin paso por EUR.
- **Rendimiento**: staking, intereses, rebates u otro ingreso en cripto
  distinto de compraventa.
- **Custodio**: entidad extranjera donde el usuario mantiene activos a
  efectos del Modelo 721.
- **Aproximación fiscal**: simplificación de cálculo cuando el dato exacto
  no está disponible. Toda aproximación cae bajo el apartado 10.

---

## 13. Relación con otros documentos

Este documento responde qué y por qué: misión, ecosistema, gobierno. No
responde cómo trabajamos (`ENGINEERING_PRINCIPLES.md`) ni qué hay
construido hoy (`ARCHITECTURE.md`). Las decisiones puntuales ya tomadas
viven en `docs/decisions/` (ADRs).

Si este documento entra en conflicto con otro sobre propósito o gobierno,
este documento tiene prioridad. Si el conflicto es sobre estado técnico
actual, `ARCHITECTURE.md` tiene prioridad — y si eso ocurre, este documento
tiene una afirmación que no debería estar aquí (ver apartado 0).
