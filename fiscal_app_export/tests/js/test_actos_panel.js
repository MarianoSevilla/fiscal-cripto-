/*
 * Test del inventario de actos (I19/I20/T6/T7) y del núcleo de PanelActo
 * en node — sin DOM. Ejecutado desde pytest (TestFilaYPanel).
 *
 * Verifica:
 *  - los cuatro actos de la fila con sus nombres literales del protocolo;
 *  - zonas de T6: Activar · [Cuestionar · Enriquecer] · Aplazar;
 *  - Cuestionar: tres niveles, cada uno con su consecuencia (I20b);
 *  - Aplazar: tres razones; el campo de condición SOLO con convicción
 *    insuficiente, con su etiqueta literal (I20c);
 *  - ningún dígito ni «%» en nombres, consecuencias y etiquetas;
 *  - el modelo del panel precarga la condición vigente al re-Aplazar
 *    (única precarga de línea, D13.5) y rechaza genéricos de confirmación.
 */
"use strict";

const path = require("path");
const base = path.join(__dirname, "..", "..", "static", "stats-v2");
const Actos = require(path.join(base, "actos.js"));
const PanelActo = require(path.join(base, "panel-acto.js"));

let fallos = 0;
function comprobar(condicion, mensaje) {
  if (!condicion) {
    console.error("FALLO: " + mensaje);
    fallos += 1;
  }
}

// ── Zonas de T6 ───────────────────────────────────────────────────────────────
comprobar(
  JSON.stringify(Actos.ZONAS) === JSON.stringify([["activar"], ["cuestionar", "enriquecer"], ["aplazar"]]),
  "las zonas no son las de I19/T6"
);

// ── Nombres literales (D13/I8) ────────────────────────────────────────────────
const NOMBRES = { activar: "Activar", cuestionar: "Cuestionar", enriquecer: "Enriquecer", aplazar: "Aplazar" };
for (const [id, nombre] of Object.entries(NOMBRES)) {
  comprobar(Actos.ACTOS[id] && Actos.ACTOS[id].nombre === nombre,
    "nombre no literal para " + id);
}
// Descartar existe como acto pero JAMÁS en las zonas de la fila (I19/T6)
comprobar("descartar" in Actos.ACTOS, "falta el acto Descartar (fase 8)");
comprobar(Actos.ZONAS.flat().indexOf("descartar") === -1,
  "Descartar no puede estar en la fila (I19)");
comprobar(!Actos.ACTOS.descartar.selector && !Actos.ACTOS.descartar.carga,
  "Descartar no lleva selector ni carga (02/D13)");
comprobar(Actos.ACTOS.descartar.consecuencia.indexOf("no desaparece") !== -1,
  "la consecuencia de Descartar debe incluir lo que NO es ([05·VII])");

// ── Sin dígitos ni % en ningún texto del inventario ───────────────────────────
function textosDe(acto) {
  const t = [acto.nombre, acto.consecuencia];
  if (acto.carga) t.push(acto.carga.etiqueta);
  if (acto.selector) {
    t.push(acto.selector.etiqueta);
    acto.selector.opciones.forEach((o) => {
      t.push(o.nombre, o.consecuencia);
      if (o.cargaCondicional) t.push(o.cargaCondicional.etiqueta);
    });
  }
  return t;
}
for (const acto of Object.values(Actos.ACTOS)) {
  for (const texto of textosDe(acto)) {
    comprobar(Boolean(texto), "texto vacío en " + acto.id);
    comprobar(!/[0-9%]/.test(texto), "dígito o % en el inventario: «" + texto + "»");
  }
}

// ── Cuestionar: tres niveles con consecuencia (I20b) ──────────────────────────
const niveles = Actos.ACTOS.cuestionar.selector.opciones.map((o) => o.id);
comprobar(
  JSON.stringify(niveles) === JSON.stringify(["observacion", "interpretacion", "implicacion"]),
  "los niveles de Cuestionar no son los tres de [06·C4]"
);

// ── Aplazar: tres razones; condición solo con convicción insuficiente ─────────
const razones = Actos.ACTOS.aplazar.selector.opciones;
comprobar(razones.length === 3, "Aplazar no tiene tres razones");
for (const razon of razones) {
  if (razon.id === "conviccion-insuficiente") {
    comprobar(Boolean(razon.cargaCondicional && razon.cargaCondicional.requerida),
      "convicción insuficiente sin campo de condición requerido (I20c)");
    comprobar(razon.cargaCondicional.etiqueta === "¿Qué necesitarías saber para reconsiderar?",
      "la etiqueta de la condición no es la literal de I20c");
  } else {
    comprobar(!razon.cargaCondicional, "campo de condición fuera de convicción insuficiente: " + razon.id);
  }
}

// ── Activar: gesto único — sin selector ni carga ──────────────────────────────
comprobar(!Actos.ACTOS.activar.selector && !Actos.ACTOS.activar.carga,
  "Activar debe ser gesto único (09 §7)");
comprobar(Actos.ACTOS.enriquecer.carga && Actos.ACTOS.enriquecer.carga.requerida,
  "Enriquecer sin carga requerida");

// ── PanelActo: precarga de condición vigente al re-Aplazar (I20c/D13.5) ───────
const conCondicion = PanelActo._modelo(Actos.ACTOS.aplazar, {
  condicion_vigente: "Saber si la caída persiste fuera de la campaña.",
});
const opcionCI = conCondicion.selector.opciones.find((o) => o.id === "conviccion-insuficiente");
comprobar(opcionCI.cargaCondicional.precarga === "Saber si la caída persiste fuera de la campaña.",
  "re-Aplazar no precarga la condición vigente");
const sinCondicion = PanelActo._modelo(Actos.ACTOS.aplazar, {});
comprobar(
  sinCondicion.selector.opciones.find((o) => o.id === "conviccion-insuficiente").cargaCondicional.precarga === "",
  "hay precarga sin condición vigente — memoria no autorizada (D13.5)"
);

// ── Genéricos de confirmación prohibidos (T7) ─────────────────────────────────
for (const generico of ["Aceptar", "Enviar", "Guardar", "Confirmar", "OK"]) {
  let lanzo = false;
  try {
    PanelActo._modelo({ id: "x", nombre: generico, consecuencia: "c" }, {});
  } catch (e) {
    lanzo = true;
  }
  comprobar(lanzo, "no rechaza el nombre genérico: " + generico);
}

if (fallos > 0) {
  console.error(fallos + " fallo(s)");
  process.exit(1);
}
console.log("actos/panel: OK — zonas, nombres literales, niveles y razones, condición literal, precarga única, genéricos rechazados");
