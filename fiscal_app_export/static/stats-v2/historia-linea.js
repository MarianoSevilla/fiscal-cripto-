/*
 * HistoriaLinea — el estrato al alcance (D11, I18).
 *
 * Reglas congeladas que este componente materializa:
 *  - I18: al pie de la línea expandida vive UNA única revelación: «Historia
 *    de esta línea». Un gesto la despliega DENTRO de la línea. Nada de la
 *    historia se co-presenta por defecto; nada exige salir de la línea.
 *  - El registro se lee DESDE EL ORIGEN: la primera entrada es el
 *    nacimiento y cada una es consecuencia de las anteriores ([T01],
 *    [06·C13]). Este componente jamás reordena ni invierte.
 *  - Es el ÚNICO lugar del producto donde puede vivir la evidencia gráfica
 *    (I2): las series se dibujan aquí como SVG sobrio, subordinadas a la
 *    entrada del registro que las interpreta. Ningún otro archivo del silo
 *    crea gráficos (vigilado por test).
 *  - Revelar no es reversible durante el encuentro — misma doctrina que el
 *    abordaje de la línea: lo revelado permanece; sin acordeón.
 *
 * El núcleo (_modelo) es puro y sin DOM para verificarse en node.
 */
(function (raiz) {
  "use strict";

  var ROTULO = "Historia de esta línea";

  function normalizarEvidencia(ev, indice) {
    if (!ev) return null;
    if (ev.tipo === "serie") {
      if (!Array.isArray(ev.puntos) || ev.puntos.length < 2) {
        throw new Error("HistoriaLinea: una serie necesita al menos dos puntos (entrada " + indice + ")");
      }
      return { tipo: "serie", descripcion: ev.descripcion || "", series: [{ nombre: null, puntos: ev.puntos }] };
    }
    if (ev.tipo === "comparativa") {
      if (!Array.isArray(ev.series) || ev.series.length < 2) {
        throw new Error("HistoriaLinea: una comparativa necesita al menos dos series (entrada " + indice + ")");
      }
      var series = ev.series.map(function (s) {
        if (!s.nombre || !Array.isArray(s.puntos) || s.puntos.length < 2) {
          throw new Error("HistoriaLinea: serie comparativa sin nombre o sin puntos (entrada " + indice + ")");
        }
        return { nombre: s.nombre, puntos: s.puntos };
      });
      return { tipo: "comparativa", descripcion: ev.descripcion || "", series: series };
    }
    throw new Error("HistoriaLinea: tipo de evidencia desconocido: " + ev.tipo);
  }

  function modelo(linea) {
    if (!linea || !Array.isArray(linea.historia) || linea.historia.length === 0) {
      throw new Error("HistoriaLinea: sin registro no hay estrato al alcance (I18)");
    }
    /* El orden llega desde el origen y se conserva tal cual: invertirlo
       convertiría el razonamiento en log — la degradación que [T01] prohíbe. */
    var entradas = linea.historia.map(function (e, i) {
      if (!e.cuando || !e.entrada) {
        throw new Error("HistoriaLinea: entrada de registro incompleta (índice " + i + ")");
      }
      return { cuando: e.cuando, texto: e.entrada, evidencia: normalizarEvidencia(e.evidencia, i) };
    });
    return { rotulo: ROTULO, entradas: entradas };
  }

  /* Trazado sobrio de una serie como polilínea SVG — solo tinta, sin ejes,
     sin cifras dibujadas. El detalle numérico vive en la prosa del registro. */
  function svgEvidencia(evidencia) {
    var NS = "http://www.w3.org/2000/svg";
    var todos = [];
    evidencia.series.forEach(function (s) { todos = todos.concat(s.puntos); });
    var min = Math.min.apply(null, todos);
    var max = Math.max.apply(null, todos);
    var rango = (max - min) || 1;

    var svg = document.createElementNS(NS, "svg");
    svg.setAttribute("viewBox", "0 0 100 40");
    svg.setAttribute("preserveAspectRatio", "none");
    svg.setAttribute("role", "img");
    svg.setAttribute("aria-label", evidencia.descripcion);

    evidencia.series.forEach(function (s, indice) {
      var n = s.puntos.length;
      var coordenadas = s.puntos.map(function (v, i) {
        var x = (i / (n - 1)) * 100;
        var y = 36 - ((v - min) / rango) * 32; /* margen vertical de 4 */
        return x.toFixed(2) + "," + y.toFixed(2);
      }).join(" ");
      var linea = document.createElementNS(NS, "polyline");
      linea.setAttribute("points", coordenadas);
      linea.setAttribute("fill", "none");
      linea.setAttribute("stroke", "currentColor");
      linea.setAttribute("stroke-width", "1.5");
      linea.setAttribute("vector-effect", "non-scaling-stroke");
      /* La segunda serie se distingue por trazo, nunca por color semántico. */
      if (indice > 0) linea.setAttribute("stroke-dasharray", "4 3");
      svg.appendChild(linea);
    });
    return svg;
  }

  function nodoEvidencia(evidencia) {
    var figura = document.createElement("figure");
    figura.className = "registro-evidencia";
    figura.appendChild(svgEvidencia(evidencia));

    var pie = document.createElement("figcaption");
    var texto = evidencia.descripcion;
    if (evidencia.tipo === "comparativa") {
      texto += " — trazo continuo: " + evidencia.series[0].nombre +
               " · trazo discontinuo: " + evidencia.series[1].nombre;
    }
    pie.textContent = texto;
    figura.appendChild(pie);
    return figura;
  }

  function crear(linea) {
    var m = modelo(linea);

    var cont = document.createElement("div");
    cont.className = "historia-linea";

    var revelacion = document.createElement("button");
    revelacion.type = "button";
    revelacion.className = "historia-revelacion";
    revelacion.textContent = m.rotulo;
    revelacion.setAttribute("aria-expanded", "false");

    var registro = document.createElement("ol");
    registro.className = "historia-registro";
    registro.hidden = true;
    if (linea.id) {
      registro.id = linea.id + "-historia";
      revelacion.setAttribute("aria-controls", registro.id);
    }

    m.entradas.forEach(function (entrada) {
      var item = document.createElement("li");
      item.className = "registro-entrada";

      var cuando = document.createElement("p");
      cuando.className = "registro-cuando";
      cuando.textContent = entrada.cuando;
      item.appendChild(cuando);

      var texto = document.createElement("p");
      texto.className = "registro-texto";
      texto.textContent = entrada.texto;
      item.appendChild(texto);

      if (entrada.evidencia) {
        item.appendChild(nodoEvidencia(entrada.evidencia));
      }
      registro.appendChild(item);
    });

    /* Un único gesto revela; lo revelado permanece durante el encuentro. */
    revelacion.addEventListener("click", function () {
      if (!registro.hidden) return;
      registro.hidden = false;
      revelacion.setAttribute("aria-expanded", "true");
      cont.classList.add("historia-revelada");
    });

    cont.appendChild(revelacion);
    cont.appendChild(registro);
    return cont;
  }

  var API = { crear: crear, _modelo: modelo, ROTULO: ROTULO };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = API; /* tests en node */
  }
  if (raiz) {
    raiz.HistoriaLinea = API;
  }
})(typeof window !== "undefined" ? window : null);
