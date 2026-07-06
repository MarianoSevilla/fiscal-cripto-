/*
 * FilaDeActos — la fila de actos y la mecánica del gesto (I19, T6, D13).
 *
 * Tres zonas por distancia, izquierda a derecha: Activar · [Cuestionar ·
 * Enriquecer] · Aplazar (I19/T6). Descartar no está en la fila (fase 8).
 * El repertorio lo trae el dato (`linea.actos`, D12/T6): este componente
 * no recorta ni amplía — si un estado excluye un acto, el dato no lo trae.
 *
 * Ciclo de vida del gesto (D13, construcción bajo pliego):
 *  - abrir el panel de un acto realiza la elección de marco (D13.1);
 *  - cada línea es un contexto de juicio con a lo sumo un gesto (D13.2);
 *  - iniciar otro acto sustituye al gesto en preparación (D13.3);
 *  - el mismo gesto sobre el mismo acto lo retira (D13.4) — aria-expanded
 *    alternante sobre el control, sin botón genérico de cierre;
 *  - el panel se monta siempre desde cero: la carga muere con su gesto
 *    (D13.5), sin memoria de borradores.
 */
(function (raiz) {
  "use strict";

  function crear(linea, gestor) {
    var actos = raiz.ActosStatsV2.ACTOS;
    var zonas = raiz.ActosStatsV2.ZONAS;
    var disponibles = linea.actos || [];

    /* El gestor del gesto es del CONTEXTO de juicio (la línea, D13.2):
       llega compartido con ControlDescartar; en solitario se crea propio. */
    gestor = gestor || raiz.GestorGestoLinea.crear();

    var contenedor = document.createElement("div");
    contenedor.className = "fila-actos-contenedor";

    var fila = document.createElement("div");
    fila.className = "fila-actos";
    fila.setAttribute("role", "group");
    fila.setAttribute("aria-label", "Actos");

    /* El hueco donde vive el panel-en-gesto: bajo la fila, dentro de la línea */
    var hueco = document.createElement("div");
    hueco.className = "fila-panel-hueco";

    function elegirMarco(id, boton) {
      gestor.alternar(id, boton, hueco, function () {
        return raiz.PanelActo.crear(actos[id], linea, function (eleccion) {
          /* Consumación (D13.1): transición + constancia (D14/I21); la
             línea re-renderiza donde está — el evento sube hasta la
             entrada y hasta el encuentro. */
          var resultado = raiz.ConsumarActo.consumar(linea, id, eleccion);
          contenedor.dispatchEvent(new CustomEvent("statsv2:consumada", {
            bubbles: true,
            detail: { linea: linea, resultado: resultado }
          }));
        });
      });
    }

    zonas.forEach(function (zona) {
      var presentes = zona.filter(function (id) {
        return disponibles.indexOf(id) !== -1 && actos[id];
      });
      if (presentes.length === 0) return;
      var grupo = document.createElement("div");
      grupo.className = "fila-zona";
      presentes.forEach(function (id) {
        var boton = document.createElement("button");
        boton.type = "button";
        boton.className = "acto acto-" + id + (id === "activar" ? " acto-relleno" : "");
        boton.textContent = actos[id].nombre;
        boton.setAttribute("aria-expanded", "false");
        boton.addEventListener("click", function () {
          elegirMarco(id, boton);
        });
        grupo.appendChild(boton);
      });
      fila.appendChild(grupo);
    });

    contenedor.appendChild(fila);
    contenedor.appendChild(hueco);
    return contenedor;
  }

  var API = { crear: crear };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = API;
  }
  if (raiz) {
    raiz.FilaDeActos = API;
  }
})(typeof window !== "undefined" ? window : null);
