/*
 * Test del núcleo de EntradaLinea (E2/I15) en node — sin DOM.
 * Se ejecuta desde pytest (test_stats_v2_page.py::TestEntradaLinea).
 *
 * Verifica:
 *  - la marca ① solo existe si hay novedad, y es la etiqueta textual (I7);
 *  - la implicación ② y la solidez ③ son obligatorias — el par se juzga
 *    unido: sin cualquiera de las dos no hay entrada (I15);
 *  - los metadatos ④+⑤ componen «estado · pertenencia», estado primero (E2);
 *  - ningún dígito ni «%» en marca ni metadatos del fixture de prueba;
 *  - la solidez pasa intacta al modelo (EntradaLinea no la interpreta).
 */
"use strict";

const path = require("path");
const EntradaLinea = require(
  path.join(__dirname, "..", "..", "static", "stats-v2", "entrada-linea.js")
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
  implicacion: "La cohorte en prueba saldrá sin convertir si nada cambia antes de que expire su ventana.",
  solidez: { lectura: "en-construccion", implicacion: "consistente" },
  novedad: { etiqueta: "nuevo", origen: "espontaneo" },
  estado_como_acto: "pendiente de tu posición",
  pertenencia: "evaluada hoy junto a otra línea",
};

// ── Anatomía completa ─────────────────────────────────────────────────────────
const m = EntradaLinea._modelo(base);
comprobar(m.marca === "nuevo", "la marca no es la etiqueta textual de la novedad");
comprobar(m.implicacion === base.implicacion, "la implicación no es el texto primario");
comprobar(m.solidez === base.solidez, "la solidez no pasa intacta al modelo");
comprobar(
  m.metadatos === "pendiente de tu posición · evaluada hoy junto a otra línea",
  "los metadatos no componen «estado · pertenencia» con el estado primero: «" + m.metadatos + "»"
);

// ── La marca solo si aplica (I7: lo que no ha cambiado no lleva marca) ────────
const sinNovedad = EntradaLinea._modelo(Object.assign({}, base, { novedad: null }));
comprobar(sinNovedad.marca === null, "hay marca sin novedad");

// ── Marca de respuesta: el origen legible en la etiqueta ([08·C2]) ────────────
const respuesta = EntradaLinea._modelo(Object.assign({}, base, {
  novedad: { etiqueta: "respuesta a tu cuestionamiento", origen: "respuesta" },
}));
comprobar(
  respuesta.marca === "respuesta a tu cuestionamiento",
  "la etiqueta de respuesta no conserva el origen legible"
);

// ── Sin implicación o sin solidez no hay entrada (I15) ────────────────────────
for (const campo of ["implicacion", "solidez"]) {
  let lanzo = false;
  try {
    const rota = Object.assign({}, base);
    delete rota[campo];
    EntradaLinea._modelo(rota);
  } catch (e) {
    lanzo = true;
  }
  comprobar(lanzo, "no rechaza una entrada sin " + campo);
}

// ── Sin dígitos ni % en los textos propios de la entrada ─────────────────────
for (const texto of [m.marca, m.metadatos, respuesta.marca]) {
  comprobar(
    !/[0-9%]/.test(texto),
    "dígito o % en texto de la entrada: «" + texto + "»"
  );
}

if (fallos > 0) {
  console.error(fallos + " fallo(s)");
  process.exit(1);
}
console.log("entrada-linea: OK — anatomía, marca condicional, origen legible, obligatoriedad del par de juicio");
