/*
 * BandaLinea — construcción de las bandas de línea (T12, CONGELADO).
 *
 * Toda banda es un bloque de superficie leve en la cabecera de la
 * expansión, con la familia del acto o estado que la produjo: Aplazar
 * fría, Descartar sepia, neutra el resto. La condición declarada viaja
 * como segunda frase de la banda que porta la razón. Sin borde, radio,
 * icono ni filete lateral.
 *
 * El tratamiento de coste NO se construye aquí: reservado a E3 (I22).
 */
(function (raiz) {
  "use strict";

  var FAMILIAS = ["aplazar", "descartar", "neutra"];

  function modelo(banda) {
    if (!banda || !banda.texto) {
      throw new Error("BandaLinea: una banda sin texto no declara nada");
    }
    var familia = banda.familia || "neutra";
    if (FAMILIAS.indexOf(familia) === -1) {
      throw new Error("BandaLinea: familia desconocida (T12): " + familia);
    }
    return {
      tipo: banda.tipo || "constancia",
      familia: familia,
      texto: banda.texto,
      segunda: banda.segunda || null
    };
  }

  function crear(banda) {
    var m = modelo(banda);
    var nodo = document.createElement("div");
    nodo.className = "banda-linea banda-" + m.tipo + " familia-" + m.familia;

    var texto = document.createElement("p");
    texto.textContent = m.texto;
    nodo.appendChild(texto);

    if (m.segunda) {
      var segunda = document.createElement("p");
      segunda.className = "banda-segunda";
      segunda.textContent = m.segunda;
      nodo.appendChild(segunda);
    }
    return nodo;
  }

  var API = { crear: crear, _modelo: modelo, FAMILIAS: FAMILIAS };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = API; /* tests en node */
  }
  if (raiz) {
    raiz.BandaLinea = API;
  }
})(typeof window !== "undefined" ? window : null);
