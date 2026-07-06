/*
 * Test del núcleo de HistoriaLinea (I18) en node — sin DOM.
 * Se ejecuta desde pytest (test_stats_v2_page.py::TestHistoriaLinea).
 *
 * Verifica:
 *  - el registro conserva el orden DESDE EL ORIGEN — jamás se invierte
 *    ([T01]: el hilo es causal, no un log);
 *  - sin registro (o vacío) no hay estrato al alcance → error;
 *  - entradas incompletas (sin cuando o sin texto) → error;
 *  - evidencia 'serie' y 'comparativa' normalizadas; tipos desconocidos,
 *    series sin nombre o con menos de dos puntos → error;
 *  - el rótulo es exactamente «Historia de esta línea», sin dígitos ni «%».
 */
"use strict";

const path = require("path");
const HistoriaLinea = require(
  path.join(__dirname, "..", "..", "static", "stats-v2", "historia-linea.js")
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
  historia: [
    {
      cuando: "hace 4 días",
      entrada: "Nace la línea: detecto una desviación sostenida.",
      evidencia: { tipo: "serie", descripcion: "serie de prueba", puntos: [3, 2, 4, 1] },
    },
    { cuando: "hace 2 días", entrada: "Evalúo causas sin poder aislar una.", evidencia: null },
    {
      cuando: "hoy",
      entrada: "Te presento la línea.",
      evidencia: {
        tipo: "comparativa",
        descripcion: "comparativa de prueba",
        series: [
          { nombre: "con integración", puntos: [46, 44, 47] },
          { nombre: "sin integración", puntos: [15, 14, 16] },
        ],
      },
    },
  ],
};

// ── Orden desde el origen, jamás invertido ────────────────────────────────────
const m = HistoriaLinea._modelo(base);
comprobar(m.entradas.length === 3, "número de entradas incorrecto");
comprobar(
  m.entradas[0].texto.indexOf("Nace la línea") === 0,
  "la primera entrada del modelo no es el nacimiento: el registro se invirtió"
);
comprobar(m.entradas[2].cuando === "hoy", "la última entrada no es la más reciente");

// ── Rótulo exacto, sin dígitos ni % ──────────────────────────────────────────
comprobar(m.rotulo === "Historia de esta línea", "rótulo incorrecto: " + m.rotulo);
comprobar(!/[0-9%]/.test(m.rotulo), "dígito o % en el rótulo");

// ── Evidencias normalizadas ───────────────────────────────────────────────────
const serie = m.entradas[0].evidencia;
comprobar(serie.tipo === "serie" && serie.series.length === 1, "serie mal normalizada");
comprobar(serie.series[0].puntos.length === 4, "puntos de la serie perdidos");
comprobar(m.entradas[1].evidencia === null, "evidencia nula no se conserva como nula");
const comparativa = m.entradas[2].evidencia;
comprobar(
  comparativa.tipo === "comparativa" && comparativa.series.length === 2,
  "comparativa mal normalizada"
);
comprobar(
  comparativa.series[0].nombre === "con integración",
  "el nombre de la serie no se conserva"
);

// ── Rechazos ──────────────────────────────────────────────────────────────────
const casosInvalidos = [
  ["sin historia", { id: "x" }],
  ["historia vacía", { id: "x", historia: [] }],
  ["entrada sin cuando", { historia: [{ entrada: "texto" }] }],
  ["entrada sin texto", { historia: [{ cuando: "hoy" }] }],
  ["evidencia de tipo desconocido", { historia: [{ cuando: "hoy", entrada: "t", evidencia: { tipo: "tabla" } }] }],
  ["serie con un solo punto", { historia: [{ cuando: "hoy", entrada: "t", evidencia: { tipo: "serie", puntos: [1] } }] }],
  ["comparativa con serie sin nombre", { historia: [{ cuando: "hoy", entrada: "t", evidencia: { tipo: "comparativa", series: [{ puntos: [1, 2] }, { nombre: "b", puntos: [1, 2] }] } }] }],
];
for (const [nombre, caso] of casosInvalidos) {
  let lanzo = false;
  try {
    HistoriaLinea._modelo(caso);
  } catch (e) {
    lanzo = true;
  }
  comprobar(lanzo, "no rechaza: " + nombre);
}

if (fallos > 0) {
  console.error(fallos + " fallo(s)");
  process.exit(1);
}
console.log("historia-linea: OK — orden desde el origen, rótulo exacto, evidencias normalizadas, rechazos");
