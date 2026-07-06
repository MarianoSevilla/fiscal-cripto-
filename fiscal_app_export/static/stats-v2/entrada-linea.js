/*
 * EntradaLinea — composición canónica de E2 (11 §5.2, CONGELADO) sobre la
 * anatomía de I15.
 *
 * Los cinco elementos, en la única disposición válida:
 *   ① marca de novedad y origen — encabeza la entrada SOLO si aplica (I7):
 *      etiqueta textual con el acento de novedad, mismo rango que el juicio.
 *   ② implicación — texto primario: frase de acción posible, nunca
 *      título-etiqueta ni métrica (I15.1).
 *   ③ SolidezDual compacta — contigua a ②: entre ambas solo --esp-1; el par
 *      se juzga unido, la solidez jamás es descubrimiento posterior.
 *   ④ estado-como-acto y ⑤ pertenencia — una sola línea de metadatos al
 *      pie, atenuada, estado primero, separados por « · ». No alimentan
 *      el juicio.
 *
 * La entrada NO es tarjeta (I2): sin borde, sin fondo, sin sombra — prosa
 * estructurada en la columna. Toda la entrada es superficie del gesto de
 * abordar (I13); la expansión llega en fase 5.
 *
 * El núcleo (_modelo) es puro y sin DOM para verificarse en node.
 */
(function (raiz) {
  "use strict";

  function modelo(linea) {
    if (!linea || !linea.implicacion) {
      throw new Error("EntradaLinea: falta la implicación — no hay entrada sin posición condensada (I15)");
    }
    if (!linea.solidez) {
      throw new Error("EntradaLinea: falta la solidez — el par implicación+solidez se juzga unido (I15)");
    }
    var metadatos = [linea.estado_como_acto, linea.pertenencia]
      .filter(function (parte) { return Boolean(parte); })
      .join(" · ");
    return {
      id: linea.id,
      marca: linea.novedad ? linea.novedad.etiqueta : null,
      implicacion: linea.implicacion,
      solidez: linea.solidez,
      metadatos: metadatos
    };
  }

  function crear(linea, opciones) {
    var m = modelo(linea);
    var abordada = Boolean(opciones && opciones.abordada);

    var item = document.createElement("li");
    item.className = "entrada-linea";
    if (m.id) item.id = m.id;

    /* Toda la entrada es superficie del gesto de abordar (I13): el punto
       de acceso es un botón que expande la línea EN EL SITIO (I16). */
    var acceso = document.createElement("button");
    acceso.type = "button";
    acceso.className = "entrada-acceso";
    acceso.setAttribute("aria-expanded", "false");

    /* ① la marca encabeza cuando existe — primera línea, antes del juicio */
    if (m.marca) {
      var marca = document.createElement("span");
      marca.className = "entrada-marca";
      marca.textContent = m.marca;
      acceso.appendChild(marca);
    }

    /* ② + ③ el bloque de juicio: contiguos, nada se interpone */
    var implicacion = document.createElement("span");
    implicacion.className = "entrada-implicacion";
    implicacion.textContent = m.implicacion;
    acceso.appendChild(implicacion);
    acceso.appendChild(raiz.SolidezDual.compacta(m.solidez));

    /* ④ + ⑤ los metadatos cierran la entrada, atenuados */
    if (m.metadatos) {
      var metadatos = document.createElement("span");
      metadatos.className = "entrada-metadatos";
      metadatos.textContent = m.metadatos;
      acceso.appendChild(metadatos);
    }

    item.appendChild(acceso);

    /* La expansión (I16): bajo la entrada, dentro de la columna y del
       conjunto. La entrada permanece visible — y con ella la pertenencia
       (I12). Sin navegación, sin desplazamiento del scroll, sin robo de
       foco: el foco queda donde el gesto ocurrió. */
    var expansion = raiz.LineaExpandida.crear(linea);
    expansion.hidden = true;
    if (m.id) {
      expansion.id = m.id + "-expansion";
      acceso.setAttribute("aria-controls", expansion.id);
    }
    item.appendChild(expansion);

    /* Abordar no es reversible durante el encuentro: la línea abordada
       entra en la conversación y permanece en ella. Sin repliegue, sin
       control de cerrar, sin acordeón — varias líneas pueden permanecer
       expandidas a la vez (corrección del responsable del producto,
       fase 5). */
    function abordar() {
      expansion.hidden = false;
      acceso.setAttribute("aria-expanded", "true");
      item.classList.add("entrada-abordada");
    }

    acceso.addEventListener("click", function () {
      if (!expansion.hidden) return;
      abordar();
    });

    /* La línea abordada tras una consumación sigue abordada (la
       permanencia es del estrato, no del gesto). */
    if (abordada) abordar();

    /* Consumación de un acto de esta línea (D14/I21): la línea
       re-renderiza inmediatamente a su nuevo estado, EN SU SITIO, con la
       banda de constancia en cabecera. El foco viaja a la constancia —
       la consecuencia se encuentra donde el gesto termina ([07·C9]). */
    item.addEventListener("statsv2:consumada", function (evento) {
      var nueva = crear(evento.detail.linea, { abordada: true });
      item.replaceWith(nueva);
      var constancia = nueva.querySelector(".banda-constancia");
      if (constancia) {
        constancia.setAttribute("tabindex", "-1");
        constancia.focus();
      }
    });

    return item;
  }

  var API = { crear: crear, _modelo: modelo };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = API; /* tests en node */
  }
  if (raiz) {
    raiz.EntradaLinea = API;
  }
})(typeof window !== "undefined" ? window : null);
