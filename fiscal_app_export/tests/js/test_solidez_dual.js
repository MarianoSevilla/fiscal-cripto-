/*
 * Test del núcleo de SolidezDual (E1 v0.4) en node — sin DOM.
 * Se ejecuta desde pytest (test_stats_v2_page.py::TestSolidezDual) y sale
 * con código != 0 si algo falla.
 *
 * Verifica sobre las 16 combinaciones de niveles:
 *  - orden fijo lectura → implicación (I9);
 *  - ningún dígito ni «%» en ningún texto del componente (I9);
 *  - las cuatro palabras de nivel exactas de I9;
 *  - nombre accesible «solidez de la <dimensión>: <nivel>»;
 *  - rechazo de niveles no categóricos (p. ej. un porcentaje).
 */
"use strict";

const path = require("path");
const SolidezDual = require(
  path.join(__dirname, "..", "..", "static", "stats-v2", "solidez-dual.js")
);

let fallos = 0;
function comprobar(condicion, mensaje) {
  if (!condicion) {
    console.error("FALLO: " + mensaje);
    fallos += 1;
  }
}

const NIVELES = SolidezDual.NIVELES;
comprobar(
  JSON.stringify(NIVELES) ===
    JSON.stringify(["fragil", "en-construccion", "consistente", "solida"]),
  "los cuatro niveles no son los congelados"
);

// ── 16 combinaciones ──────────────────────────────────────────────────────────
for (const lectura of NIVELES) {
  for (const implicacion of NIVELES) {
    const m = SolidezDual._modelo({ lectura, implicacion });
    comprobar(m.length === 2, "el modelo no tiene dos dimensiones");
    comprobar(
      m[0].dimension === "lectura" && m[1].dimension === "implicacion",
      "orden de dimensiones distinto del de I9"
    );
    for (const d of m) {
      for (const texto of [d.palabraDimension, d.palabraNivel, d.aria]) {
        comprobar(
          !/[0-9%]/.test(texto),
          "dígito o % en la interfaz de convicción: «" + texto + "»"
        );
      }
    }
  }
}

// ── Palabras de nivel exactas (I9) ────────────────────────────────────────────
const esperadas = ["frágil", "en construcción", "consistente", "sólida"];
NIVELES.forEach((nivel, i) => {
  const palabra = SolidezDual._modelo({ lectura: nivel, implicacion: nivel })[0].palabraNivel;
  comprobar(
    palabra === esperadas[i],
    "palabra de nivel incorrecta para " + nivel + ": «" + palabra + "»"
  );
});

// ── Nombre accesible ──────────────────────────────────────────────────────────
const a = SolidezDual._modelo({ lectura: "consistente", implicacion: "fragil" });
comprobar(a[0].aria === "solidez de la lectura: consistente", "aria de lectura incorrecto");
comprobar(a[1].aria === "solidez de la implicación: frágil", "aria de implicación incorrecto");

// ── Rechazo de niveles no categóricos ─────────────────────────────────────────
for (const invalido of ["70%", "0.7", "alta", null, undefined]) {
  let lanzo = false;
  try {
    SolidezDual._modelo({ lectura: invalido, implicacion: "solida" });
  } catch (e) {
    lanzo = true;
  }
  comprobar(lanzo, "no rechaza el nivel no categórico: " + invalido);
}

if (fallos > 0) {
  console.error(fallos + " fallo(s)");
  process.exit(1);
}
console.log("solidez-dual: OK — 16 combinaciones, palabras de nivel, aria y rechazo de no-categóricos");
