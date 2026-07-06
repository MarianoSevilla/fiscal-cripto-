/*
 * SolidezDual — E1 v0.4 (11-design-system.md §5.1, CONGELADO): la palabra
 * portadora. Cada dimensión es un signo indivisible: su nombre en versalitas
 * con un subrayado de materia que porta el nivel.
 *
 * Reglas congeladas que este componente materializa:
 *  - Dos dimensiones, «lectura» primero e «implicación» después (orden de la
 *    enumeración de I9; composición estable, sin carga semántica).
 *  - Cuatro niveles SOLO como materia: discontinuo → continuo → media tinta
 *    → tinta plena. El color no participa. La longitud del subrayado la fija
 *    la palabra, jamás el nivel.
 *  - Números y porcentajes prohibidos en todo nodo del componente.
 *  - Palabras de nivel (frágil · en construcción · consistente · sólida)
 *    solo en la forma expandida.
 *  - Ninguna relación geométrica entre los dos signos (regla de expresión
 *    geométrica, 11 §2): sin contacto, solape ni desplazamiento.
 *  - Accesibilidad: cada signo porta nombre accesible completo
 *    («solidez de la lectura: consistente») — atributo, no píxel.
 *
 * El núcleo (_modelo) es puro y sin DOM para poder verificarse en node
 * (tests/js/test_solidez_dual.js).
 */
(function (raiz) {
  "use strict";

  var NIVELES = ["fragil", "en-construccion", "consistente", "solida"];

  var PALABRA_NIVEL = {
    "fragil": "frágil",
    "en-construccion": "en construcción",
    "consistente": "consistente",
    "solida": "sólida"
  };

  var DIMENSIONES = [
    { clave: "lectura", palabra: "lectura" },
    { clave: "implicacion", palabra: "implicación" }
  ];

  function modelo(solidez) {
    return DIMENSIONES.map(function (dim) {
      var nivel = solidez ? solidez[dim.clave] : undefined;
      if (NIVELES.indexOf(nivel) === -1) {
        throw new Error(
          "SolidezDual: nivel no categórico para «" + dim.palabra + "»: " + nivel
        );
      }
      return {
        dimension: dim.clave,
        palabraDimension: dim.palabra,
        nivel: nivel,
        palabraNivel: PALABRA_NIVEL[nivel],
        aria: "solidez de la " + dim.palabra + ": " + PALABRA_NIVEL[nivel]
      };
    });
  }

  /* Un signo: palabra portadora + subrayado de materia. */
  function signo(m) {
    var s = document.createElement("span");
    s.className = "sd-signo sd-nivel-" + m.nivel;
    s.setAttribute("role", "img");
    s.setAttribute("aria-label", m.aria);

    var palabra = document.createElement("span");
    palabra.className = "sd-palabra";
    palabra.setAttribute("aria-hidden", "true");
    palabra.textContent = m.palabraDimension;

    var materia = document.createElement("span");
    materia.className = "sd-materia";
    materia.setAttribute("aria-hidden", "true");

    s.appendChild(palabra);
    s.appendChild(materia);
    return s;
  }

  /* Compacta: los dos signos en una línea, misma línea base, sin relación
     dibujada. Sin palabras de nivel. */
  function compacta(solidez) {
    var c = document.createElement("span");
    c.className = "solidez-dual";
    modelo(solidez).forEach(function (m) {
      c.appendChild(signo(m));
    });
    return c;
  }

  /* Expandida: los dos signos a 1.5×, apilados a ras del mismo margen, con
     la palabra de su nivel alineada a una vertical común. */
  function expandida(solidez) {
    var c = document.createElement("div");
    c.className = "solidez-dual-expandida";
    modelo(solidez).forEach(function (m) {
      c.appendChild(signo(m));
      var nivel = document.createElement("span");
      nivel.className = "sd-palabra-nivel";
      /* El aria del signo ya declara dimensión y nivel: el texto visible
         no se anuncia dos veces. */
      nivel.setAttribute("aria-hidden", "true");
      nivel.textContent = m.palabraNivel;
      c.appendChild(nivel);
    });
    return c;
  }

  var API = {
    compacta: compacta,
    expandida: expandida,
    NIVELES: NIVELES,
    _modelo: modelo
  };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = API; /* tests en node */
  }
  if (raiz) {
    raiz.SolidezDual = API;
  }
})(typeof window !== "undefined" ? window : null);
