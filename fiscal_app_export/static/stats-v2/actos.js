/*
 * Actos — inventario de los actos de la fila y sus paneles (Fase 7).
 *
 * Fuentes de autoridad:
 *  - Nombres literales del protocolo (D13/I8): sin sinónimos.
 *  - Frases de consecuencia: contenido del Lenguaje de Interacción (02),
 *    en la voz del sistema (I8: primera persona; jamás imperativos sobre
 *    la decisión). T11 (Entrega 4) consolidará el inventario definitivo;
 *    hasta entonces este módulo toma el contenido de 02 tal cual (T7 §6).
 *  - Selector de nivel de Cuestionar y de razón de Aplazar con la
 *    consecuencia de cada opción siempre visible (I20b/c, T7).
 *  - El campo de condición con convicción insuficiente y su etiqueta
 *    literal (I20c).
 *  - Zonas de la fila (I19/T6): Activar · [Cuestionar · Enriquecer] ·
 *    Aplazar. Descartar NO está en la fila (fase 8, control propio).
 */
(function (raiz) {
  "use strict";

  var ZONAS = [["activar"], ["cuestionar", "enriquecer"], ["aplazar"]];

  var ACTOS = {
    activar: {
      id: "activar",
      nombre: "Activar",
      consecuencia:
        "Transformo la oportunidad en una intervención en diseño y entro " +
        "en observación del espacio que delimita.",
      selector: null,
      carga: null
    },
    cuestionar: {
      id: "cuestionar",
      nombre: "Cuestionar",
      consecuencia:
        "Reevalúo mi razonamiento en el nivel que cuestiones; tu objeción " +
        "queda dentro del gesto.",
      selector: {
        etiqueta: "Hacia dónde apunta tu desacuerdo",
        opciones: [
          {
            id: "observacion",
            nombre: "La observación",
            consecuencia:
              "Reviso mi base de evidencia; mi convicción queda en revisión " +
              "hasta que la reevalúe."
          },
          {
            id: "interpretacion",
            nombre: "La interpretación",
            consecuencia:
              "Reduzco la convicción de mi hipótesis actual y busco " +
              "interpretaciones alternativas para el mismo patrón."
          },
          {
            id: "implicacion",
            nombre: "La implicación",
            consecuencia:
              "Reviso el nivel de urgencia sin alterar la convicción de la " +
              "hipótesis."
          }
        ]
      },
      carga: { id: "objecion", etiqueta: "Tu objeción", requerida: false }
    },
    enriquecer: {
      id: "enriquecer",
      nombre: "Enriquecer",
      consecuencia:
        "Incorporo tu contexto a la memoria de este área — persiste más " +
        "allá de la sesión — y reevalúo mi convicción a su luz.",
      selector: null,
      carga: { id: "contexto", etiqueta: "El contexto que aportas", requerida: true }
    },
    aplazar: {
      id: "aplazar",
      nombre: "Aplazar",
      consecuencia:
        "Registro tu aplazamiento con su razón; la razón determina lo que " +
        "sigo haciendo.",
      selector: {
        etiqueta: "La razón del aplazamiento",
        opciones: [
          {
            id: "ejecucion",
            nombre: "Restricción de ejecución",
            consecuencia:
              "Mantengo la urgencia activa: sigo midiendo si la ventana " +
              "permanece abierta."
          },
          {
            id: "estrategia",
            nombre: "Decisión estratégica",
            consecuencia: "Suspendo el escalado y mantengo la hipótesis viva."
          },
          {
            id: "conviccion-insuficiente",
            nombre: "Convicción insuficiente",
            consecuencia:
              "Suspendo la urgencia y el escalado: no volveré a presentarte " +
              "esta línea por iniciativa propia hasta que mi evidencia sea " +
              "materialmente más sólida.",
            cargaCondicional: {
              id: "condicion",
              etiqueta: "¿Qué necesitarías saber para reconsiderar?",
              requerida: true
            }
          }
        ]
      },
      carga: null
    },
    /* Descartar NO pertenece a la fila (I19): su control vive al pie,
       tras la historia (T6). Su consecuencia legible incluye lo que NO es
       ([05·VII]): no elimina la evidencia. */
    descartar: {
      id: "descartar",
      nombre: "Descartar",
      consecuencia:
        "Cierro esta interpretación. La evidencia no desaparece: la " +
        "preservo sin interpretar, disponible para una lectura futura " +
        "distinta.",
      selector: null,
      carga: null
    }
  };

  var API = { ZONAS: ZONAS, ACTOS: ACTOS };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = API; /* tests en node */
  }
  if (raiz) {
    raiz.ActosStatsV2 = API;
  }
})(typeof window !== "undefined" ? window : null);
