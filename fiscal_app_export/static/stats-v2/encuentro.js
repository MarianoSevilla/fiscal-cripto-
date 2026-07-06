/*
 * /stats-v2 — Render del encuentro (Fase 2 del Hito 1).
 *
 * Consume el contrato de datos servido por /api/stats-v2/encuentro
 * (fase 2: fixture del escenario 02; el contrato está documentado en
 * fiscal_app_export/stats_v2_fixture.py y es el que el razonamiento real
 * deberá cumplir).
 *
 * Fase 2 renderiza el esqueleto: cabecera, declaración conjunta, la
 * implicación de cada entrada como prosa provisional, Ancla y Pausa.
 * La anatomía completa de la entrada (E2/I15), SolidezDual (E1), la
 * expansión (I16–I18) y los actos (I19–I21) llegan en las fases 3–8.
 *
 * Todo el contenido se inserta con textContent — nunca innerHTML.
 */
(async function () {
  let encuentro;
  try {
    const r = await fetch("/api/stats-v2/encuentro", { credentials: "same-origin" });
    if (!r.ok) return;
    encuentro = await r.json();
  } catch (_) {
    return;
  }

  const set = (id, texto) => {
    const nodo = document.getElementById(id);
    if (nodo && texto) nodo.textContent = texto;
  };

  set("ancla-texto", encuentro.ancla && encuentro.ancla.texto);
  set("convocatoria", encuentro.cabecera && encuentro.cabecera.convocatoria);
  set("continuidad", encuentro.cabecera && encuentro.cabecera.continuidad);
  set("declaracion-conjunta", encuentro.declaracion_conjunta);
  set("pausa-texto", encuentro.pausa && encuentro.pausa.texto);

  // Entradas en el orden recibido: el orden ES la urgencia del sistema y
  // nada más (I13) — el cliente jamás reordena.
  const lista = document.getElementById("entradas");
  (encuentro.lineas || []).forEach((linea) => {
    lista.appendChild(window.EntradaLinea.crear(linea));
  });

  // I4: llegadas y periferia solo se muestran si existen. En fase 2 el
  // fixture las trae vacías: las regiones permanecen ocultas.
  if ((encuentro.llegadas || []).length > 0) {
    document.getElementById("region-llegadas").hidden = false;
  }
  if ((encuentro.periferia || []).length > 0) {
    document.getElementById("periferia").hidden = false;
  }

  // ── Consecuencias de encuentro de una consumación (fase 8) ──────────────
  // El Ancla dice la verdad vigente (I14b/D16.5) y la Pausa declara su
  // cuenta (I29). Actualización textual sobre las bandas provisionales del
  // esqueleto — construcción definitiva en T5/T2 (hito 2).
  document.addEventListener("statsv2:consumada", (evento) => {
    const { linea, resultado } = evento.detail;
    if (!resultado.posicional) return;

    if (encuentro.ancla && linea.id === encuentro.ancla.linea_id) {
      encuentro.ancla.estado = "satisfecha";
      set("ancla-texto", "Lo impostergable de hoy tiene posición.");
      document.getElementById("ancla").classList.add("ancla-satisfecha");
    }

    // Sin posición = pendiente o en reevaluación (la reevaluación no es
    // una posición del responsable del producto).
    const sinPosicion = (encuentro.lineas || []).filter(
      (l) => l.estado === "pendiente-de-posicion" || l.estado === "en-reevaluacion"
    ).length;
    if (sinPosicion === 0) {
      encuentro.pausa.estado = "disponible";
      set("pausa-texto", "Lo presentado hoy tiene posición.");
    } else {
      set("pausa-texto", sinPosicion === 1
        ? "Queda 1 línea de hoy sin posición."
        : "Quedan " + sinPosicion + " líneas de hoy sin posición.");
    }
  });
})();
