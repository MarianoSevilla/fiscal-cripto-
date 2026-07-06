/*
 * ConsumarActo — la elección consumante (D13.1) y su constancia (D14/I21).
 *
 * Módulo puro de datos: aplica al objeto línea la transición que el
 * protocolo fija para cada acto (02 «Estado producido»; 09 §14) y produce
 * la constancia — la voz del sistema declarando lo que ahora hace (I8/I21),
 * con la familia visual que T12 asigna (Aplazar fría, Descartar sepia,
 * neutras el resto). La condición declarada viaja como segunda frase de la
 * banda que porta la razón (T12) y queda como condición vigente de la
 * línea (habilita la precarga de I20c en un re-Aplazar).
 *
 * Los repertorios post-acto son datos del protocolo (D12): en fase 8 los
 * fija este módulo sobre el fixture; el razonamiento real los servirá por
 * el mismo contrato.
 *
 * `posicional` marca los actos que dan posición a la línea (Activar,
 * Aplazar, Descartar) — lo que satisface al Ancla (I14b) y descuenta en la
 * Pausa (I29). Cuestionar y Enriquecer son diálogo: no posicionan.
 */
(function (raiz) {
  "use strict";

  var REPERTORIO_INTEGRO = ["activar", "cuestionar", "enriquecer", "aplazar", "descartar"];

  var TEXTOS_CUESTIONAR = {
    "observacion": "Cuestionaste la observación — estoy reevaluando mi base de evidencia.",
    "interpretacion": "Cuestionaste la interpretación — estoy reevaluando qué significa el patrón.",
    "implicacion": "Cuestionaste la implicación — estoy reevaluando el nivel de urgencia."
  };

  var TEXTOS_APLAZAR = {
    "ejecucion": "Aplazada por restricción de ejecución — sigo midiendo si la ventana permanece abierta.",
    "estrategia": "Aplazada por decisión estratégica — suspendo el escalado y mantengo la hipótesis viva.",
    "conviccion-insuficiente": "Aplazada por convicción insuficiente — oriento mi observación a la condición que declaraste."
  };

  var ESTADO_COMO_ACTO_APLAZAR = {
    "ejecucion": "aplazada — sigo midiendo la ventana",
    "estrategia": "aplazada — mantengo la hipótesis viva",
    "conviccion-insuficiente": "aplazada — esperando la señal que pediste"
  };

  function consumar(linea, actoId, eleccion) {
    eleccion = eleccion || {};
    var constancia;
    var posicional = false;

    switch (actoId) {
      case "activar":
        linea.estado = "en-intervencion";
        linea.estado_como_acto = "en observación desde hoy";
        linea.actos = ["cuestionar", "enriquecer"];
        constancia = {
          familia: "neutra",
          texto: "He transformado la oportunidad en una intervención: observo este espacio desde hoy con el propósito que la activación define."
        };
        posicional = true;
        break;

      case "aplazar": {
        var razon = eleccion.opcion;
        if (!TEXTOS_APLAZAR[razon]) {
          throw new Error("ConsumarActo: Aplazar exige su razón dentro del gesto ([06·C5])");
        }
        linea.estado = "aplazada";
        linea.estado_como_acto = ESTADO_COMO_ACTO_APLAZAR[razon];
        linea.actos = REPERTORIO_INTEGRO.slice(); /* revisitarla reabre la posición (09 §14) */
        constancia = { familia: "aplazar", texto: TEXTOS_APLAZAR[razon] };
        if (razon === "conviccion-insuficiente") {
          var condicion = ((eleccion.textos || {}).condicion || "").trim();
          if (!condicion) {
            throw new Error("ConsumarActo: convicción insuficiente exige la condición declarada (I20c)");
          }
          linea.condicion_vigente = condicion;      /* precarga de I20c en el re-Aplazar */
          constancia.segunda = "Condición declarada: " + condicion;
        }
        posicional = true;
        break;
      }

      case "cuestionar": {
        var nivel = eleccion.opcion;
        if (!TEXTOS_CUESTIONAR[nivel]) {
          throw new Error("ConsumarActo: Cuestionar exige su nivel dentro del gesto ([06·C4])");
        }
        linea.estado = "en-reevaluacion";
        linea.estado_como_acto = "reevaluando lo que cuestionaste";
        linea.actos = REPERTORIO_INTEGRO.slice(); /* íntegro, incluida la activación (05·IV, D12) */
        constancia = { familia: "neutra", texto: TEXTOS_CUESTIONAR[nivel] };
        break;
      }

      case "enriquecer":
        /* 02: el enriquecimiento no cambia el estado; el marco se actualiza
           y la convicción se reevalúa. */
        constancia = {
          familia: "neutra",
          texto: "He incorporado tu contexto a la memoria de este área — mi convicción queda reevaluada a su luz."
        };
        break;

      case "descartar":
        linea.estado = "cerrada";
        linea.estado_como_acto = "cerrada — evidencia preservada";
        linea.actos = []; /* el área sigue consultable (D9); sin actos de línea */
        constancia = {
          familia: "descartar",
          texto: "Cerrada la interpretación — la evidencia queda preservada, sin interpretar, disponible para una lectura futura distinta."
        };
        posicional = true;
        break;

      default:
        throw new Error("ConsumarActo: acto desconocido: " + actoId);
    }

    /* D14: la constancia es propiedad de la línea el resto del encuentro (I21) */
    linea.constancia = constancia;

    return { constancia: constancia, posicional: posicional };
  }

  var API = { consumar: consumar };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = API; /* tests en node */
  }
  if (raiz) {
    raiz.ConsumarActo = API;
  }
})(typeof window !== "undefined" ? window : null);
