/*
 * ControlDescartar — el acto de archivo (I19, T6, [06·C6], [05·VII]).
 *
 * Descartar no está en la fila: vive solo, al pie de la línea, tras la
 * revelación de historia, con forma de control de archivo — texto en la
 * familia sepia, sin contorno ni relleno, jamás par visual de un botón.
 * Su panel-en-gesto se despliega bajo el control (T7) y participa del
 * MISMO contexto de juicio que la fila (D13.2): comparte gestor.
 */
(function (raiz) {
  "use strict";

  function crear(linea, gestor) {
    var contenedor = document.createElement("div");
    contenedor.className = "control-descartar-contenedor";

    var control = document.createElement("button");
    control.type = "button";
    control.className = "control-descartar";
    control.textContent = raiz.ActosStatsV2.ACTOS.descartar.nombre;
    control.setAttribute("aria-expanded", "false");

    var hueco = document.createElement("div");
    hueco.className = "descartar-panel-hueco";

    control.addEventListener("click", function () {
      gestor.alternar("descartar", control, hueco, function () {
        return raiz.PanelActo.crear(
          raiz.ActosStatsV2.ACTOS.descartar,
          linea,
          function (eleccion) {
            var resultado = raiz.ConsumarActo.consumar(linea, "descartar", eleccion);
            contenedor.dispatchEvent(new CustomEvent("statsv2:consumada", {
              bubbles: true,
              detail: { linea: linea, resultado: resultado }
            }));
          }
        );
      });
    });

    contenedor.appendChild(control);
    contenedor.appendChild(hueco);
    return contenedor;
  }

  var API = { crear: crear };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = API;
  }
  if (raiz) {
    raiz.ControlDescartar = API;
  }
})(typeof window !== "undefined" ? window : null);
