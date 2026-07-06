/*
 * Test del módulo de consumación (D13.1, D14, I21, T12) en node — sin DOM.
 * Ejecutado desde pytest (TestConsumacion).
 *
 * Verifica, por acto:
 *  - la transición de estado del protocolo (02 «Estado producido», 09 §14);
 *  - el repertorio post-acto (D12: íntegro tras Cuestionar — incluida la
 *    activación, 05·IV —; reabierto tras Aplazar; vacío tras Descartar);
 *  - la constancia con su familia de T12 (Aplazar fría, Descartar sepia,
 *    neutras el resto) y sin dígitos ni «%»;
 *  - convicción insuficiente: condición obligatoria, registrada como
 *    condicion_vigente (precarga de I20c) y como segunda frase (T12);
 *  - `posicional` solo en Activar/Aplazar/Descartar;
 *  - rechazo de acto desconocido y de Aplazar/Cuestionar sin su elección.
 */
"use strict";

const path = require("path");
const Consumar = require(
  path.join(__dirname, "..", "..", "static", "stats-v2", "consumar.js")
);

let fallos = 0;
function comprobar(condicion, mensaje) {
  if (!condicion) {
    console.error("FALLO: " + mensaje);
    fallos += 1;
  }
}

function lineaBase() {
  return {
    id: "linea-prueba",
    estado: "pendiente-de-posicion",
    estado_como_acto: "pendiente de tu posición",
    actos: ["activar", "cuestionar", "enriquecer", "aplazar", "descartar"],
    bandas: { razon: null, procedencia: null, coste: null },
  };
}

// ── Activar ───────────────────────────────────────────────────────────────────
let l = lineaBase();
let r = Consumar.consumar(l, "activar", {});
comprobar(l.estado === "en-intervencion", "Activar no transforma en intervención");
comprobar(r.posicional === true, "Activar debe ser posicional");
comprobar(r.constancia.familia === "neutra", "constancia de Activar no neutra");
comprobar(l.constancia === r.constancia, "la constancia no queda en la línea (I21)");

// ── Aplazar por cada razón ────────────────────────────────────────────────────
for (const razon of ["ejecucion", "estrategia"]) {
  l = lineaBase();
  r = Consumar.consumar(l, "aplazar", { opcion: razon });
  comprobar(l.estado === "aplazada", "Aplazar no aplaza (" + razon + ")");
  comprobar(r.constancia.familia === "aplazar", "constancia de Aplazar sin familia fría (T12)");
  comprobar(l.actos.length === 5, "la línea aplazada no reabre el repertorio (09 §14)");
  comprobar(!r.constancia.segunda, "segunda frase sin condición declarada");
  comprobar(r.posicional === true, "Aplazar debe ser posicional");
}

l = lineaBase();
r = Consumar.consumar(l, "aplazar", {
  opcion: "conviccion-insuficiente",
  textos: { condicion: "Saber si la caída persiste fuera de la campaña." },
});
comprobar(l.condicion_vigente === "Saber si la caída persiste fuera de la campaña.",
  "la condición no queda vigente (I20c/D13.5)");
comprobar(Boolean(r.constancia.segunda) && r.constancia.segunda.indexOf("Condición declarada") === 0,
  "la condición no viaja como segunda frase de la banda (T12)");
comprobar(l.estado_como_acto === "aplazada — esperando la señal que pediste",
  "estado-como-acto de convicción insuficiente no es el de I15");

let lanzo = false;
try { Consumar.consumar(lineaBase(), "aplazar", { opcion: "conviccion-insuficiente", textos: {} }); }
catch (e) { lanzo = true; }
comprobar(lanzo, "no exige la condición con convicción insuficiente");

// ── Cuestionar por cada nivel ─────────────────────────────────────────────────
for (const nivel of ["observacion", "interpretacion", "implicacion"]) {
  l = lineaBase();
  r = Consumar.consumar(l, "cuestionar", { opcion: nivel });
  comprobar(l.estado === "en-reevaluacion", "Cuestionar no reevalúa (" + nivel + ")");
  comprobar(l.actos.indexOf("activar") !== -1,
    "el repertorio en reevaluación excluye Activar — contradice 05·IV/D12");
  comprobar(r.constancia.texto.indexOf("Cuestionaste") === 0,
    "la constancia no es constancia del acto del responsable (I28/D14)");
  comprobar(r.posicional === false, "Cuestionar no posiciona");
}

// ── Enriquecer: sin cambio de estado ──────────────────────────────────────────
l = lineaBase();
r = Consumar.consumar(l, "enriquecer", { textos: { contexto: "Contexto de prueba." } });
comprobar(l.estado === "pendiente-de-posicion", "Enriquecer no debe cambiar el estado (02)");
comprobar(r.posicional === false, "Enriquecer no posiciona");

// ── Descartar ─────────────────────────────────────────────────────────────────
l = lineaBase();
r = Consumar.consumar(l, "descartar", {});
comprobar(l.estado === "cerrada", "Descartar no cierra");
comprobar(l.actos.length === 0, "la línea cerrada conserva actos de línea");
comprobar(r.constancia.familia === "descartar", "constancia de Descartar sin familia sepia (T12/[06·C6])");
comprobar(r.constancia.texto.indexOf("preservada") !== -1,
  "la constancia de Descartar no declara la preservación ([05·VII])");
comprobar(r.posicional === true, "Descartar debe ser posicional");

// ── Sin dígitos ni % en ninguna constancia ────────────────────────────────────
const casos = [
  ["activar", {}], ["aplazar", { opcion: "ejecucion" }],
  ["cuestionar", { opcion: "interpretacion" }], ["enriquecer", {}], ["descartar", {}],
];
for (const [acto, eleccion] of casos) {
  const res = Consumar.consumar(lineaBase(), acto, eleccion);
  comprobar(!/[0-9%]/.test(res.constancia.texto),
    "dígito o % en la constancia de " + acto);
}

// ── Rechazos ──────────────────────────────────────────────────────────────────
for (const [acto, eleccion] of [["publicar", {}], ["cuestionar", {}], ["aplazar", {}]]) {
  let fallo = false;
  try { Consumar.consumar(lineaBase(), acto, eleccion); } catch (e) { fallo = true; }
  comprobar(fallo, "no rechaza: " + acto + " con elección " + JSON.stringify(eleccion));
}

if (fallos > 0) {
  console.error(fallos + " fallo(s)");
  process.exit(1);
}
console.log("consumar: OK — transiciones, repertorios, constancias con familia, condición vigente, posicionalidad y rechazos");
