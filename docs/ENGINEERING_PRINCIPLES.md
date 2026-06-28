# ENGINEERING_PRINCIPLES.md
### Cómo trabajamos — y cómo decidimos cuándo algo está terminado

## 0. Vigencia
- Creado: 2026-06-25. Última revisión: 2026-06-25.
- Se revisa cuando cambia la metodología de trabajo, no cuando cambia el
  código. Si el código cambia pero la forma de decidir y de trabajar sigue
  siendo la misma, este documento no se toca — eso es `ARCHITECTURE.md`.

---

## 1. Principios de ingeniería que nunca se negocian

1. Ningún cambio que pueda alterar el resultado fiscal mostrado al usuario
   se considera completo sin pasar por la validación de gobierno de
   `PROJECT_IDENTITY.md` (apartados 5 y 10) — corregir un error también
   altera ese resultado, no solo añadir una función lo hace.
2. Ninguna fuente de datos externa nueva se incorpora sin datos reales de
   esa fuente para probarla. Un dato sintético reproduce lo que el autor
   del componente imagina que la fuente entrega, no lo que realmente
   entrega — y esa diferencia es, en este proyecto, donde han vivido casi
   todos los defectos encontrados hasta hoy. (Hoy, esto significa
   exchanges de criptomonedas y los ficheros que exportan.)
3. Ningún componente de salida compartido por varias fuentes o canales se
   modifica directamente para dar soporte a uno nuevo si existe una vía de
   extenderlo sin tocar el camino de los que ya funcionan. La razón es de
   coste de error, no de elegancia de código: una regresión en un
   componente compartido rompe silenciosamente todo lo que ya funcionaba,
   a la vez.
4. Ninguna actualización de una dependencia externa se mezcla con una
   corrección funcional en el mismo cambio. Son dos clases de riesgo
   distintas y deben poder revertirse de forma independiente.
5. Ninguna variable de configuración crítica para la integridad del
   sistema tiene un comportamiento de repliegue silencioso en producción.
   O el sistema arranca con lo necesario, o no arranca.

---

## 2. Principios de decisión

Este apartado no añade reglas — explica cómo razonar cuando dos
principios de este documento, o de `PROJECT_IDENTITY.md`, parecen pedir
cosas distintas en un caso real. El objetivo es que quien lo lea aprenda a
pensar como se piensa en este proyecto, no que memorice una lista más
larga.

- **Cuando un principio de corrección choca con uno de velocidad, gana la
  corrección — pero "ganar" no significa "no se lanza nunca".** Significa
  que la limitación conocida se comunica (principio fundacional 3 de
  `PROJECT_IDENTITY.md`) en vez de fingir que no existe.
- **Cuando dos reglas de este documento parecen aplicar a la vez y piden
  cosas distintas, el desempate no es "¿qué regla pesa más en general?"
  sino "¿cuál de las dos protege más directamente el resultado fiscal del
  usuario?".** Ese eje decide, no la antigüedad de la regla ni la
  comodidad de aplicarla en ese momento.
- **Ante la duda de si algo requiere escalar a la validación de gobierno
  de `PROJECT_IDENTITY.md`, la pregunta correcta nunca es "¿esto es difícil
  técnicamente?".** Es "¿esto puede cambiar lo que el usuario ve como su
  resultado fiscal, o el rumbo de negocio?". Dificultad técnica y
  necesidad de escalar son ejes independientes.
- **Cuando una regla de este documento deja de tener sentido frente a un
  caso real, la respuesta no es ignorarla en silencio ni inventar una
  excepción ad hoc.** Es seguir la regla vigente mientras se registra la
  tensión como propuesta de ADR — ver también el apartado 17.
- **Ante un caso nuevo sin regla explícita, se razona desde los principios
  fundacionales de `PROJECT_IDENTITY.md` hacia abajo, no desde la
  implementación más parecida hacia arriba.** La pregunta es "¿qué exige
  la misión y la jerarquía de calidad aquí?", no "¿qué hicimos la última
  vez en un caso que se parecía a este?".

---

## 3. Auditoría obligatoria

Una auditoría formal — no un análisis de impacto puntual, ver apartado
siguiente — es obligatoria antes de: incorporar una fuente de datos
externa nueva, modificar el componente que calcula el resultado fiscal,
modificar el componente que genera una presentación formal ante una
administración pública, o después de cualquier incidente que haya
alterado el resultado fiscal mostrado a un usuario real.

Responde, como mínimo: qué cambia, qué deja de ser cierto de lo que el
sistema asumía hasta ahora, qué datos reales la sustentan, y qué severidad
(apartado 8 de `PROJECT_IDENTITY.md`) tendría el peor escenario si el
cambio resultara incorrecto.

El resultado se conserva como snapshot fechado en `docs/audits/` —
**nunca se descarta tras leerlo una vez, ni siquiera si todos sus
hallazgos se resuelven el mismo día.** El coste de omitir una auditoría
obligatoria no lo paga quien decide omitirla — lo paga el usuario que
presenta un resultado fiscal incorrecto sin saberlo. Esa asimetría es la
razón de que esto no quede a discreción de cada cambio.

---

## 4. Análisis de impacto antes de modificar código

Antes de tocar cualquier fichero, se identifica explícitamente qué otros
componentes consumen lo que va a cambiar. Un componente de ingesta
alimenta al motor de cálculo, que alimenta a los documentos de salida del
sistema — modificar uno sin trazar los demás es, en la historia de este
proyecto, el patrón de error más repetido.

El análisis de impacto no es un documento que se redacta — es una
pregunta que se responde antes de escribir la primera línea, no después.
Si responderla deja una incertidumbre genuina sobre qué podría romperse,
esa incertidumbre es la señal de que el cambio necesita la auditoría
obligatoria del apartado 3, no solo este análisis.

> Nota de ubicación: el mapa real de qué componente depende de cuál vive
> en `ARCHITECTURE.md`. Este apartado exige consultarlo y razonar sobre
> él; no lo reproduce.

---

## 5. Control de versiones y revisión de cambios

Ningún cambio que module el resultado fiscal se mezcla, en el mismo
conjunto de cambios, con uno de interfaz, contenido o adquisición — son
riesgos de naturaleza distinta y deben poder revertirse de forma
independiente. Una corrección en el cálculo o en la ingesta de datos
nunca se integra sin que conste explícitamente si altera resultados ya
calculados para usuarios existentes: esa respuesta determina si necesita
la validación de gobierno de `PROJECT_IDENTITY.md` antes de desplegarse,
no después de que ya esté en producción.

Un historial que mezcla tipos de riesgo distintos en un solo cambio obliga,
para revertir lo que salió mal, a revertir también lo que funcionaba.

> Nota de ubicación: convenciones operativas concretas del sistema de
> control de versiones en uso son instrucción operativa de `CLAUDE.md`,
> no principio de este documento.

---

## 6. Seguridad

Ningún fichero entregado por un usuario se procesa antes de validar su
tamaño real una vez expandido, no solo su tamaño aparente — un fichero de
datos puede ser, internamente, un formato comprimido, y agotar la memoria
del proceso con un fichero pequeño pero muy comprimido es, en este
sistema, un riesgo real detectado, no hipotético.

Ninguna variable de configuración crítica para la integridad de los datos
tiene un valor por defecto utilizable en producción. Ningún secreto se
incorpora al control de versiones, ni siquiera temporalmente "para
probar" — no existe en este proyecto una categoría de secreto de bajo
riesgo, porque el sistema maneja datos fiscales de usuarios reales.

Este apartado no repite una lista genérica de buenas prácticas: las
reglas que importan aquí son las que ya se han demostrado explotables en
este sistema. Una lista genérica no habría detectado ninguna de ellas.

> Nota de ubicación: los vectores concretos ya identificados y su estado
> de corrección viven en `docs/audits/`; cuando se resuelven de forma
> permanente, se registran como ADR.

---

## 7. Despliegue y entorno de producción

Ninguna variable de configuración necesaria para la integridad del
sistema en producción tiene repliegue silencioso — el patrón correcto es
el ya aplicado a la clave de firma de sesión: si falta, el sistema no
arranca. Cualquier excepción a esto debe ser una decisión consciente y
documentada, nunca un descuido heredado.

Ningún despliegue a producción ocurre sin que la suite de pruebas se haya
ejecutado y haya pasado completa — lo que presupone, como condición
previa y no como consecuencia, que esa suite es ejecutable de principio a
fin.

El proveedor de infraestructura actual es un hecho de arquitectura, no un
principio: si cambia, este documento no debería necesitar reescritura —
solo la sección correspondiente de `ARCHITECTURE.md`.

Un sistema que degrada en silencio ante una configuración incompleta
convierte un simple error de despliegue en pérdida de datos o en un
servicio inseguro, en lugar de en una alerta visible e inmediata.

---

## 8. Persistencia de datos

Un motor de almacenamiento pensado para desarrollo local nunca sustituye
al de producción, ni siquiera temporalmente, ni como repliegue de
emergencia — los datos de un usuario sobre un almacenamiento no diseñado
para producción pueden perderse sin ningún error visible para nadie.
(Hoy, esto significa que un fichero local de base de datos nunca es
aceptable en producción; ver `ARCHITECTURE.md` para el motor vigente.)

Ningún cambio de esquema que pueda perder datos se aplica directamente en
producción sin una vía de reversión verificada de antemano.

A diferencia de un error de cálculo, que se puede corregir y recalcular,
la pérdida de datos de usuario no tiene vía de recuperación — es la única
clase de error de todo este documento que es estrictamente irreversible,
y por eso se trata con un estándar más alto que cualquier otro apartado de
infraestructura.

---

## 9. Ingesta de datos desde fuentes externas

Ninguna entrada que el sistema no reconozca se descarta sin registrar una
advertencia visible. El silencio ante un dato no reconocido es, para el
usuario, indistinguible de un cálculo correcto que simplemente no incluye
ese dato — y esa es precisamente la forma en que un error de cálculo se
vuelve invisible hasta que alguien lo audita.

El formato y la codificación de cualquier fichero de entrada nunca se
asumen — se detectan o se verifican explícitamente, incluso para una
fuente donde "siempre ha funcionado así". (Hoy, esto aplica a ficheros
exportados por exchanges de criptomonedas en distintos formatos y
codificaciones.)

> Nota de ubicación: el patrón técnico de detección, y la decisión de qué
> arquitectura sigue una fuente nueva al incorporarse, son contenido de
> `ARCHITECTURE.md` y de un ADR pendiente respectivamente. Aquí solo
> queda la regla de que nunca se asume.

---

## 10. Cálculo del resultado fiscal

Todo dato que entra al componente de cálculo debe poder trazarse de
vuelta hasta el registro original que lo originó — aplica de forma
literal el principio fundacional de auditabilidad de
`PROJECT_IDENTITY.md`. Si una agregación de datos no permite esa
trazabilidad, la agregación está mal diseñada, sin importar cuán
razonable parezca el resultado numérico que produce.

Ningún cambio a esta lógica es una "mejora técnica" pura. Es, siempre
también, un cambio en el resultado fiscal mostrado al usuario, y cae bajo
el apartado 5/10 de `PROJECT_IDENTITY.md` sin excepción.

La precisión numérica de este componente es una decisión de criterio
fiscal, no una preferencia de implementación: qué representación se usa
para las cantidades, y qué margen de error tolera, se decide con la misma
autoridad que cualquier otra aproximación fiscal — no por comodidad de
quien escribe el código.

> Nota de ubicación: el método de cálculo vigente (hoy, FIFO) y la
> precisión numérica actual son hechos de arquitectura en
> `ARCHITECTURE.md`. Si se decide cambiarlos, la decisión se registra
> como ADR.

---

## 11. Documentos de autogestión del usuario

Un documento de salida pensado para que el usuario se autogestione nunca
se genera sin un límite conocido de recursos. El riesgo dominante de este
tipo de componente no es de exactitud — ya cubierta en el apartado 10 —
sino de agotamiento de recursos ante una entrada grande: una sola
generación no debe poder degradar el servicio para el resto de usuarios.

El documento comunica siempre, de forma visible al usuario y no solo en
un metadato interno, cualquier limitación conocida del cálculo que
contiene. Esto aplica de forma literal el principio fundacional 3 de
`PROJECT_IDENTITY.md`: una limitación documentada solo en el código no
cuenta como comunicada.

Este tipo de documento se trata distinto de una presentación formal
(apartado siguiente) porque su destino es la autogestión del usuario, no
una administración pública — el criterio de calidad aquí es la honestidad
hacia el usuario, no la validación formal de un esquema externo. (Hoy,
esto corresponde al informe de cálculo FIFO en formato PDF.)

---

## 12. Presentaciones formales ante administraciones públicas

Ningún documento de este tipo se entrega sin haber pasado la validación
contra el esquema oficial correspondiente — esa es la condición mínima,
no la suficiente. Un documento técnicamente válido con datos incompletos
o no verificados se señala siempre como borrador, nunca como definitivo,
siguiendo una separación de capas — técnica, estructural, fiscal — que
nunca se colapsa entre sí. "Pasa el esquema" nunca se interpreta, ni se
comunica al usuario, como "listo para presentar".

Cualquier umbral, criterio de obligación de declarar, o tratamiento de un
tipo de activo en este tipo de documento es un criterio fiscal y cae, sin
excepción, en las decisiones reservadas al asesor fiscal colegiado de
`PROJECT_IDENTITY.md`.

Este apartado existe separado del anterior porque un defecto aquí no es
una mala experiencia de usuario — es un documento incorrecto ante una
administración pública. Cualquier incidencia se trata, por defecto, en el
nivel más alto de severidad del apartado 8 de `PROJECT_IDENTITY.md`. (Hoy,
esto corresponde al Modelo 721 y su XML ante la AEAT.)

---

## 13. Comunicación pública y experiencia de usuario

Ninguna afirmación de copy, titular o diseño promete al usuario un
resultado que el producto no pueda sostener. Esto aplica de forma literal
el principio fundacional 8 de `PROJECT_IDENTITY.md` a cualquier superficie
pública: una afirmación que insinúe una garantía de presentación ante una
administración, una rentabilidad, o una resolución completa sin matices,
es una violación de identidad — no un detalle de redacción que se corrige
más tarde si alguien se queja.

Un cambio en una superficie pública se trata con el mismo rigor de
análisis de impacto (apartado 4) que un cambio de backend cuando toca
elementos compartidos entre páginas o pantallas. El patrón de fallo ya
observado en este proyecto — un componente que se asume compartido pero
en realidad está fijado de forma independiente en cada lugar donde
aparece — es exactamente el tipo de error que un análisis de impacto
débil no detecta.

El crecimiento de alcance o la optimización para canales de adquisición
nunca se persiguen a costa de la confianza o la coherencia con la misión
— el apartado 7 de `PROJECT_IDENTITY.md` ya fija el crecimiento como el
quinto criterio de desempate, no el primero.

Esta superficie necesita reglas propias porque es la puerta de entrada a
todo el ecosistema (apartado 3 de `PROJECT_IDENTITY.md`). Un fallo de
confianza aquí arriesga el mismo activo — principio fundacional 4 — que
arriesga un fallo de cálculo, aunque el mecanismo del daño sea distinto.
(Hoy, el canal de adquisición principal es el contenido optimizado para
buscadores.)

---

## 14. Dependencias y gestión de entorno

Toda dependencia externa de producción se fija a una versión exacta
conocida. Un cambio de versión nunca entra a producción sin que alguien
lo haya decidido explícitamente — no como efecto colateral de un
despliegue cualquiera.

El código que ya no se usa no permanece indefinidamente en la rama
principal "por si acaso". Si de verdad no se usa, su sola presencia añade
incertidumbre sobre si algo vivo depende de él.

Una dependencia sin versión fijada y código muerto ambiguo son, en el
fondo, la misma clase de riesgo: incertidumbre sobre qué está realmente en
producción en un momento dado, que solo se descubre cuando algo falla.

---

## 15. Observabilidad y telemetría

Cualquier fallo de procesamiento se registra con suficiente contexto para
reproducirlo sin pedir el dato original al usuario, y sin registrar su
contenido fiscal o personal. La trazabilidad (principio fundacional 7 de
`PROJECT_IDENTITY.md`) y la privacidad del usuario no compiten aquí: ambas
se resuelven registrando metadatos del proceso, nunca los datos en sí.

Ninguna métrica relevante para una decisión de negocio o de gobierno
depende exclusivamente de un registro que rota o se pierde. Si la métrica
importa para decidir algo, se persiste donde no pueda perderse.

> Nota de ubicación: el esquema concreto de qué se registra hoy y dónde
> vive en `ARCHITECTURE.md`.

---

## 16. Definición de terminado

Un cambio se considera terminado en este proyecto cuando, y solo cuando:

- Ha pasado el análisis de impacto del apartado 4 y, si ese análisis
  reveló incertidumbre real, también la auditoría obligatoria del
  apartado 3.
- Está implementado y probado con datos reales cuando toca un componente
  de ingesta, el componente de cálculo, o cualquier generador de
  documentos de salida — no con datos sintéticos incapaces de reproducir
  la irregularidad real de una fuente externa.
- Ha sido revisado por alguien o por una sesión distinta de quien lo
  escribió, salvo que sea autonomía técnica plena sin impacto fiscal ni
  de negocio (apartado 10 de `PROJECT_IDENTITY.md`).
- No introduce ni mantiene exposición de datos sensibles — fiscales o
  personales — más allá de lo estrictamente necesario.
- No degrada la experiencia de usuario, los canales de adquisición ni la
  confianza pública cuando el cambio toca la comunicación pública
  (apartado 13).
- Si el cambio puede alterar el resultado fiscal mostrado al usuario,
  cuenta ya con la validación de gobierno de `PROJECT_IDENTITY.md`
  obtenida — no pendiente, no "se pedirá después del despliegue".
- Está verificado en el entorno real cuando el riesgo lo justifica. No
  toda corrección de copy necesita verificarse en producción, pero ningún
  cambio al cálculo, a la ingesta o a una presentación formal se considera
  terminado solo porque "pasa en local".

Un cambio que cumple seis de estos siete puntos no está casi terminado —
no está terminado. Esta definición no es un promedio: es una condición de
todo o nada, igual que la jerarquía de severidad del apartado 8 de
`PROJECT_IDENTITY.md` no admite promedios entre categorías.

---

## 17. Evolución de estos principios

Ningún principio de este documento se modifica para justificar una
excepción puntual. Si un caso real demuestra que un principio ya no es
correcto, se registra primero como ADR — describiendo el caso y por qué
el principio falla — y solo después, si procede, se actualiza este
documento. Un principio que cambia sin ese registro previo no es una
evolución: es una excepción disfrazada de regla nueva.

---

## 18. Relación con otros documentos

Este documento responde cómo trabajamos y cómo decidimos cuándo algo está
realmente terminado. No responde qué es el proyecto (`PROJECT_IDENTITY.md`)
ni qué hay construido hoy (`ARCHITECTURE.md`). Las decisiones puntuales ya
tomadas viven en `docs/decisions/` (ADRs). Las instrucciones operativas
concretas para cómo debe trabajar Claude en este repositorio viven en
`CLAUDE.md`, que se construye sobre este documento — no lo duplica.

Si este documento entra en conflicto con `PROJECT_IDENTITY.md` sobre
misión o gobierno, `PROJECT_IDENTITY.md` tiene prioridad. Si este
documento afirma un hecho concreto de implementación en vez de un
principio, esa afirmación pertenece a `ARCHITECTURE.md` y debe trasladarse
ahí.
