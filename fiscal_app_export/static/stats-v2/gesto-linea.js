/*
 * GestorGestoLinea — la unidad del gesto por contexto de juicio (D13.2–D13.5).
 *
 * Cada línea es UN contexto de juicio: su gestor es compartido por la fila
 * de actos y por el control de Descartar — abrir Descartar sustituye al
 * gesto de la fila y viceversa (D13.2, D13.3). El mismo gesto sobre el
 * mismo acto retira la elección de marco (D13.4). Los paneles se montan
 * siempre de cero: la carga muere con su gesto (D13.5).
 */
(function (raiz) {
  "use strict";

  function crear() {
    var abierto = null; /* { id, boton, panel } */

    function retirar() {
      if (!abierto) return;
      abierto.panel.remove();
      abierto.boton.setAttribute("aria-expanded", "false");
      abierto = null;
    }

    /* Realiza la elección de marco (D13.1) o la retira (D13.4);
       sustituye al gesto en preparación si lo hay (D13.3). */
    function alternar(id, boton, hueco, montarPanel) {
      if (abierto && abierto.id === id) {
        retirar();
        return;
      }
      retirar();
      var panel = montarPanel();
      hueco.appendChild(panel);
      boton.setAttribute("aria-expanded", "true");
      abierto = { id: id, boton: boton, panel: panel };
    }

    return { alternar: alternar, retirar: retirar };
  }

  var API = { crear: crear };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = API;
  }
  if (raiz) {
    raiz.GestorGestoLinea = API;
  }
})(typeof window !== "undefined" ? window : null);
