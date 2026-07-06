/*
 * LineaExpandida — el segundo estrato de la línea (D11, I16–I18).
 *
 * Reglas congeladas que este componente materializa:
 *  - I16: la expansión ocurre EN EL SITIO, dentro de la columna y del
 *    conjunto. Nunca navegación, nunca página de detalle: este archivo no
 *    toca la URL, ni el historial, ni abre ventanas, ni desplaza el scroll
 *    (vigilado por test).
 *  - I17: sin ningún gesto adicional muestra la posición tripartita rotulada
 *    en voz del sistema — «Observo» · «Interpreto» · «Esto implica» —, la
 *    SolidezDual con sus palabras (forma expandida de E1 v0.4), y las bandas
 *    de inmediatez cuando existen. Las bandas ENCABEZAN la expansión: se
 *    perciben antes que la posición.
 *  - I18: al pie vive el lugar de la única revelación, «Historia de esta
 *    línea». En fase 5 la Historia permanece cerrada: su contenedor existe,
 *    sin control visible — nada de affordance falsa hasta la fase 6.
 *  - La construcción definitiva de las bandas pertenece a T12 (Entrega 2 del
 *    DS): aquí solo prosa provisional si llegaran datos; el fixture actual
 *    no trae ninguna.
 *
 * El núcleo (_modelo) es puro y sin DOM para verificarse en node.
 */
(function (raiz) {
  "use strict";

  var SEGMENTOS = [
    { clave: "observo", rotulo: "Observo" },
    { clave: "interpreto", rotulo: "Interpreto" },
    { clave: "implica", rotulo: "Esto implica" }
  ];

  /* Orden estable de las bandas de cabecera; solo las presentes. */
  var BANDAS = ["razon", "procedencia", "coste"];

  function modelo(linea) {
    if (!linea || !linea.posicion) {
      throw new Error("LineaExpandida: falta la posición — no hay estrato inmediato sin tripartita (I17)");
    }
    if (!linea.solidez) {
      throw new Error("LineaExpandida: falta la solidez — la expandida porta sus palabras (I17)");
    }
    var segmentos = SEGMENTOS.map(function (s) {
      var texto = linea.posicion[s.clave];
      if (!texto) {
        throw new Error(
          "LineaExpandida: tripartita incompleta — falta «" + s.rotulo + "» (I17, [06·C1])"
        );
      }
      return { clave: s.clave, rotulo: s.rotulo, texto: texto };
    });
    var bandas = BANDAS.filter(function (tipo) {
      return Boolean(linea.bandas && linea.bandas[tipo]);
    }).map(function (tipo) {
      return { tipo: tipo, texto: linea.bandas[tipo] };
    });
    return { segmentos: segmentos, bandas: bandas, solidez: linea.solidez };
  }

  function crear(linea) {
    var m = modelo(linea);

    var cont = document.createElement("div");
    cont.className = "linea-expandida";

    /* Las bandas encabezan la expansión (I17/I21), construidas por T12 en
       orden de apilado constancia → razón → procedencia. El coste no se
       construye: tratamiento exclusivo reservado a E3 (I22). */
    var FAMILIA_POR_TIPO = { razon: "aplazar", procedencia: "neutra" };
    var bandasCabecera = [];
    if (linea.constancia) {
      bandasCabecera.push({
        tipo: "constancia",
        familia: linea.constancia.familia,
        texto: linea.constancia.texto,
        segunda: linea.constancia.segunda || null
      });
    }
    m.bandas.forEach(function (banda) {
      if (banda.tipo === "coste") return; /* E3 pendiente */
      bandasCabecera.push({
        tipo: banda.tipo,
        familia: FAMILIA_POR_TIPO[banda.tipo] || "neutra",
        texto: banda.texto
      });
    });
    if (bandasCabecera.length > 0) {
      var bandas = document.createElement("div");
      bandas.className = "expansion-bandas";
      bandasCabecera.forEach(function (banda) {
        bandas.appendChild(raiz.BandaLinea.crear(banda));
      });
      cont.appendChild(bandas);
    }

    /* La posición tripartita, rotulada en voz del sistema. */
    var posicion = document.createElement("div");
    posicion.className = "expansion-posicion";
    m.segmentos.forEach(function (segmento) {
      var rotulo = document.createElement("p");
      rotulo.className = "segmento-rotulo";
      rotulo.textContent = segmento.rotulo;
      var prosa = document.createElement("p");
      prosa.className = "segmento-prosa";
      prosa.textContent = segmento.texto;
      posicion.appendChild(rotulo);
      posicion.appendChild(prosa);
    });
    cont.appendChild(posicion);

    /* SolidezDual con sus palabras (E1 v0.4, forma expandida). */
    cont.appendChild(raiz.SolidezDual.expandida(m.solidez));

    /* Un solo gestor de gesto para todo el contexto de juicio (D13.2):
       lo comparten la fila y el control de Descartar. */
    var gestor = raiz.GestorGestoLinea.crear();
    var enFila = (linea.actos || []).filter(function (id) { return id !== "descartar"; });

    /* La fila de actos cierra el estrato inmediato (I19/T6). El repertorio
       lo trae el dato (D12): sin actos, sin fila — p. ej. Reportada. */
    if (enFila.length > 0) {
      cont.appendChild(raiz.FilaDeActos.crear(linea, gestor));
    }

    /* La Historia (I18): al pie de la expansión, única revelación dentro
       de la línea. */
    cont.appendChild(raiz.HistoriaLinea.crear(linea));

    /* Descartar: solo, al pie absoluto, tras la historia (I19/T6),
       compartiendo el contexto de juicio de la línea (D13.2). */
    if ((linea.actos || []).indexOf("descartar") !== -1) {
      cont.appendChild(raiz.ControlDescartar.crear(linea, gestor));
    }

    return cont;
  }

  var API = { crear: crear, _modelo: modelo };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = API; /* tests en node */
  }
  if (raiz) {
    raiz.LineaExpandida = API;
  }
})(typeof window !== "undefined" ? window : null);
