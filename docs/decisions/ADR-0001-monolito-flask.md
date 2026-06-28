# ADR-0001 — Un único proceso Flask en lugar de microservicios

**Estado:** Aceptado  
**Fecha:** 2026-06-25

## Contexto

El proyecto sirve cuatro líneas del ecosistema (herramienta FIFO, Modelo 721,
asesoramiento fiscal, contenido educativo) desde una única base de código. Todas las
líneas comparten autenticación, conexión a base de datos, lógica de precios históricos
y el motor de cálculo FIFO. El equipo es de un único desarrollador. Al volumen y
tamaño de equipo actuales, la infraestructura distribuida añadiría complejidad sin
beneficio observable.

Esta decisión se reconstruye del código — no existe documentación original del proceso
de decisión.

## Decisión

Un único proceso Flask sirve todas las líneas del ecosistema: rutas HTML, APIs,
ficheros estáticos, cálculo FIFO y generación de documentos de salida. No hay
microservicios, frontend desacoplado ni colas asíncronas. El estado técnico de esta
arquitectura está en `ARCHITECTURE.md` §2.

## Alternativas consideradas

**Microservicios (un servicio por línea del ecosistema):** las cuatro líneas comparten
autenticación, base de datos y lógica de precios históricos. Separar esas capas
requeriría comunicación inter-servicios y sincronización de esquemas sin beneficio
real al volumen y tamaño de equipo actuales.

**Frontend desacoplado (SPA + API REST):** requeriría un build step y versionado de
API que el proyecto evita deliberadamente. El frontend actual es HTML estático y
Jinja2 renderizado en servidor — un SPA añadiría complejidad para problemas que el
sistema no tiene hoy.

**Funciones serverless para el cálculo FIFO:** el motor FIFO (`MotorFIFO`) mantiene
el inventario en memoria a través de múltiples operaciones dentro de una misma
petición. Migrar ese estado a un entorno serverless requeriría serializar y deserializar
el inventario en cada invocación.

## Consecuencias

- Despliegue simple: un único servicio en Railway, sin coordinación entre servicios.
- Un solo contexto de ejecución: sin contrato de API entre capas, sin sincronización
  de esquemas entre servicios.
- El estado en memoria (concurrent analysis lock, rate limiting sin Redis) es coherente
  dentro del proceso sin infraestructura adicional.
- Todo el cómputo es síncrono en el hilo de la petición HTTP — aceptable al volumen
  actual; escalar implica manejar tiempos de cálculo en el mismo hilo de red.
- Escalar el sistema significa escalar el monolito completo, no los componentes con
  mayor carga.
- La coexistencia de líneas con naturaleza muy distinta en un único proceso crea
  presión a largo plazo hacia la separación de responsabilidades (deuda activa en
  `ARCHITECTURE.md` §16).
- La configuración de Gunicorn con un único worker (gthread, 8 threads) es consecuencia
  directa de este diseño: con múltiples workers, el estado en memoria dejaría de ser
  coherente sin Redis.
