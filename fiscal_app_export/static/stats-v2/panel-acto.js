/*
 * PanelActo — el panel-en-gesto (I20 v1.1, T7, D13).
 *
 * Anatomía fija (T7): consecuencia → selector con la consecuencia de cada
 * opción SIEMPRE visible → carga libre con etiqueta visible → confirmación
 * con el nombre literal del acto (genéricos prohibidos).
 *
 * Ciclo de vida (D13, construido en fila-actos.js): cada apertura MONTA el
 * panel desde cero a partir del Estado Compartido — la carga no consumada
 * muere con su gesto (D13.5) por construcción: no existe caché de paneles.
 * Precargas autorizadas: la condición vigente al re-Aplazar (I20c) y el
 * área de una señal (I26 — hito 3).
 *
 * La consumación (D14/I21, BandaConstancia) llega en fase 8: la
 * confirmación completa está construida pero aún no produce efecto.
 */
(function (raiz) {
  "use strict";

  var GENERICOS_PROHIBIDOS = ["aceptar", "enviar", "guardar", "confirmar", "ok"];

  function modelo(defActo, linea) {
    if (!defActo || !defActo.nombre || !defActo.consecuencia) {
      throw new Error("PanelActo: acto sin nombre o sin consecuencia (I20a)");
    }
    if (GENERICOS_PROHIBIDOS.indexOf(defActo.nombre.toLowerCase()) !== -1) {
      throw new Error("PanelActo: nombre genérico prohibido (D13/T7): " + defActo.nombre);
    }
    var carga = defActo.carga ? {
      id: defActo.carga.id,
      etiqueta: defActo.carga.etiqueta,
      requerida: Boolean(defActo.carga.requerida),
      precarga: ""
    } : null;

    var selector = null;
    if (defActo.selector) {
      selector = {
        etiqueta: defActo.selector.etiqueta,
        opciones: defActo.selector.opciones.map(function (o) {
          var cargaCondicional = o.cargaCondicional ? {
            id: o.cargaCondicional.id,
            etiqueta: o.cargaCondicional.etiqueta,
            requerida: Boolean(o.cargaCondicional.requerida),
            /* I20c: re-Aplazar precarga la condición vigente para refinarla —
               única precarga de línea autorizada (D13.5). */
            precarga: (defActo.id === "aplazar" && o.id === "conviccion-insuficiente" &&
                       linea && linea.condicion_vigente) ? linea.condicion_vigente : ""
          } : null;
          return {
            id: o.id,
            nombre: o.nombre,
            consecuencia: o.consecuencia,
            cargaCondicional: cargaCondicional
          };
        })
      };
    }
    return {
      id: defActo.id,
      nombre: defActo.nombre,
      consecuencia: defActo.consecuencia,
      selector: selector,
      carga: carga
    };
  }

  function crear(defActo, linea, alConsumar) {
    var m = modelo(defActo, linea);
    var estado = { opcion: null, textos: {} };

    var panel = document.createElement("div");
    panel.className = "panel-acto panel-" + m.id;

    /* 1 · La consecuencia encabeza el panel (I20a) */
    var consecuencia = document.createElement("p");
    consecuencia.className = "panel-consecuencia";
    consecuencia.textContent = m.consecuencia;
    panel.appendChild(consecuencia);

    var confirmacion; /* se define abajo; los handlers la actualizan */

    function completo() {
      if (m.selector && !estado.opcion) return false;
      if (m.carga && m.carga.requerida && !(estado.textos[m.carga.id] || "").trim()) return false;
      if (estado.opcion && estado.opcion.cargaCondicional && estado.opcion.cargaCondicional.requerida &&
          !(estado.textos[estado.opcion.cargaCondicional.id] || "").trim()) return false;
      return true;
    }

    function refrescarConfirmacion() {
      confirmacion.setAttribute("aria-disabled", completo() ? "false" : "true");
    }

    function campoCarga(def) {
      var etiqueta = document.createElement("label");
      etiqueta.className = "panel-carga";
      var texto = document.createElement("span");
      texto.className = "carga-etiqueta";
      texto.textContent = def.etiqueta;
      var area = document.createElement("textarea");
      area.value = def.precarga || "";
      if (def.precarga) estado.textos[def.id] = def.precarga;
      area.addEventListener("input", function () {
        estado.textos[def.id] = area.value;
        refrescarConfirmacion();
      });
      etiqueta.appendChild(texto);
      etiqueta.appendChild(area);
      return etiqueta;
    }

    /* 2 · El selector, con la consecuencia de cada opción siempre visible */
    var huecoCondicional = null;
    if (m.selector) {
      var grupo = document.createElement("div");
      grupo.className = "panel-selector";
      grupo.setAttribute("role", "radiogroup");
      grupo.setAttribute("aria-label", m.selector.etiqueta);
      var nombreGrupo = "sel-" + m.id + "-" + Math.random().toString(36).slice(2, 8);

      m.selector.opciones.forEach(function (opcion) {
        var envoltura = document.createElement("label");
        envoltura.className = "panel-opcion";
        var radio = document.createElement("input");
        radio.type = "radio";
        radio.name = nombreGrupo;
        radio.value = opcion.id;
        radio.addEventListener("change", function () {
          estado.opcion = opcion;
          grupo.querySelectorAll(".panel-opcion").forEach(function (n) {
            n.classList.remove("opcion-elegida");
          });
          envoltura.classList.add("opcion-elegida");
          /* Campo de condición: dentro del gesto, solo con su razón (I20c) */
          huecoCondicional.textContent = "";
          if (opcion.cargaCondicional) {
            huecoCondicional.appendChild(campoCarga(opcion.cargaCondicional));
          }
          refrescarConfirmacion();
        });
        var nombre = document.createElement("span");
        nombre.className = "opcion-nombre";
        nombre.textContent = opcion.nombre;
        var consecuenciaOpcion = document.createElement("span");
        consecuenciaOpcion.className = "opcion-consecuencia";
        consecuenciaOpcion.textContent = opcion.consecuencia;
        envoltura.appendChild(radio);
        envoltura.appendChild(nombre);
        envoltura.appendChild(consecuenciaOpcion);
        grupo.appendChild(envoltura);
      });
      panel.appendChild(grupo);
      huecoCondicional = document.createElement("div");
      huecoCondicional.className = "panel-carga-condicional";
      panel.appendChild(huecoCondicional);
    }

    /* 3 · La carga libre del acto, con etiqueta visible */
    if (m.carga) {
      panel.appendChild(campoCarga(m.carga));
    }

    /* 4 · La confirmación porta el nombre literal del acto (T6/T7) */
    confirmacion = document.createElement("button");
    confirmacion.type = "button";
    confirmacion.className = "acto panel-confirmacion" +
      (m.id === "activar" ? " acto-relleno" : "");
    confirmacion.textContent = m.nombre;
    confirmacion.addEventListener("click", function () {
      if (!completo()) return;      /* gesto incompleto: el paso pendiente sigue visible */
      /* La elección consumante (D13.1): el acto se consuma con su nombre. */
      if (typeof alConsumar === "function") {
        alConsumar({
          opcion: estado.opcion ? estado.opcion.id : null,
          textos: Object.assign({}, estado.textos)
        });
      }
    });
    panel.appendChild(confirmacion);
    refrescarConfirmacion();

    return panel;
  }

  var API = { crear: crear, _modelo: modelo, GENERICOS_PROHIBIDOS: GENERICOS_PROHIBIDOS };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = API; /* tests en node */
  }
  if (raiz) {
    raiz.PanelActo = API;
  }
})(typeof window !== "undefined" ? window : null);
