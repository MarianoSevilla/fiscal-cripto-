/*
 * Test del núcleo de LineaExpandida (D11, I16–I18) en node — sin DOM.
 * Se ejecuta desde pytest (test_stats_v2_page.py::TestLineaExpandida).
 *
 * Verifica:
 *  - tripartita obligatoria: falta cualquiera de los tres segmentos → error
 *    (I17, [06·C1]: tripartita siempre);
 *  - rótulos exactos en voz del sistema: «Observo» · «Interpreto» ·
 *    «Esto implica», sin dígitos ni «%»;
 *  - bandas: solo las presentes, en orden estable razón → procedencia →
 *    coste (las ausentes no generan nada — nada de bandas vacías);
 *  - la solidez pasa intacta (la expandida la delega en SolidezDual);
 *  - sin posición o sin solidez no hay estrato inmediato.
 */
"use strict";

const path = require("path");
const LineaExpandida = require(
  path.join(__dirname, "..", "..", "static", "stats-v2", "linea-expandida.js")
);

let fallos = 0;
function comprobar(condicion, mensaje) {
  if (!condicion) {
    console.error("FALLO: " + mensaje);
    fallos += 1;
  }
}

const base = {
  id: "linea-prueba",
  solidez: { lectura: "solida", implicacion: "consistente" },
  posicion: {
    observo: "El patrón se sostiene en seis meses de cohortes consecutivas.",
    interpreto: "La correlación es estable; no he confirmado causalidad.",
    implica: "Si la relación es causal, adelantar la integración es la palanca más sólida que observo.",
  },
  bandas: { razon: null, procedencia: null, coste: null },
};

// ── Tripartita completa con rótulos exactos ───────────────────────────────────
const m = LineaExpandida._modelo(base);
comprobar(m.segmentos.length === 3, "la posición no tiene tres segmentos");
const rotulos = m.segmentos.map((s) => s.rotulo);
comprobar(
  JSON.stringify(rotulos) === JSON.stringify(["Observo", "Interpreto", "Esto implica"]),
  "rótulos incorrectos: " + rotulos.join(" / ")
);
for (const r of rotulos) {
  comprobar(!/[0-9%]/.test(r), "dígito o % en un rótulo: " + r);
}
comprobar(m.solidez === base.solidez, "la solidez no pasa intacta");
comprobar(m.bandas.length === 0, "bandas nulas generan bandas");

// ── Falta un segmento → error, para cada uno de los tres ─────────────────────
for (const segmento of ["observo", "interpreto", "implica"]) {
  let lanzo = false;
  try {
    const rota = Object.assign({}, base, {
      posicion: Object.assign({}, base.posicion, { [segmento]: "" }),
    });
    LineaExpandida._modelo(rota);
  } catch (e) {
    lanzo = true;
  }
  comprobar(lanzo, "no rechaza una tripartita sin «" + segmento + "»");
}

// ── Sin posición o sin solidez → error ────────────────────────────────────────
for (const campo of ["posicion", "solidez"]) {
  let lanzo = false;
  try {
    const rota = Object.assign({}, base);
    delete rota[campo];
    LineaExpandida._modelo(rota);
  } catch (e) {
    lanzo = true;
  }
  comprobar(lanzo, "no rechaza una línea sin " + campo);
}

// ── Bandas presentes: solo esas, en orden estable ─────────────────────────────
const conBandas = LineaExpandida._modelo(Object.assign({}, base, {
  bandas: {
    coste: "Mantener el aplazamiento hasta el lunes deja fuera la cohorte de campaña.",
    razon: "Aplazada por decisión estratégica — mantengo la hipótesis viva.",
    procedencia: null,
  },
}));
comprobar(conBandas.bandas.length === 2, "número de bandas incorrecto");
comprobar(
  conBandas.bandas[0].tipo === "razon" && conBandas.bandas[1].tipo === "coste",
  "el orden de las bandas no es estable (razón → procedencia → coste)"
);

if (fallos > 0) {
  console.error(fallos + " fallo(s)");
  process.exit(1);
}
console.log("linea-expandida: OK — tripartita obligatoria, rótulos exactos, bandas presentes en orden estable");
