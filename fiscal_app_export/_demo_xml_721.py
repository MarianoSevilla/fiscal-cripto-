"""
Demo visual de los tres estados del endpoint /api/721.

Ejecutar:  python3 _demo_xml_721.py

Genera en consola:
  · Ejemplo 1 — XML BLOQUEADO  (sin NIF, sin precios)
  · Ejemplo 2 — XML BORRADOR   (NIF OK, precios OK, custodio sin ID confirmado)
  · Ejemplo 3 — XML VÁLIDO     (todos los datos completos)
  · El XML del ejemplo 3 completo impreso al final

No usa Flask ni CSVs. Solo los módulos generador_xml_721 y custodios_721.
"""

import json
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from decimal import Decimal
from generador_xml_721 import (
    validar_para_xml,
    generar_xml_721,
    ErrXMLBloqueado,
)

# ── COLORES ANSI ───────────────────────────────────────────────────────────────
RED    = "\033[31m"
YELLOW = "\033[33m"
GREEN  = "\033[32m"
CYAN   = "\033[36m"
BOLD   = "\033[1m"
RESET  = "\033[0m"


# ── HELPERS ────────────────────────────────────────────────────────────────────

def _activo(ticker, cantidad, valor_eur, denominacion=None):
    return {
        "activo":                ticker,
        "denominacion":          denominacion or ticker,
        "siglas":                ticker[:15],
        "cantidad":              cantidad,
        "valor_eur":             valor_eur,
        "origen_valor":          "O" if valor_eur else None,
        "coste_base_fifo":       "10000.00",
        "clave":                 "T",
        "origen_moneda_virtual": "A",
        "fecha_referencia":      "31-12-2024",
        "requiere_revision":     True,
        "advertencias":          [],
    }


def _exc_bitvavo(activos, confianza="media"):
    return {
        "exchange":          "Bitvavo B.V.",
        "exchange_key":      "bitvavo",
        "pais_custodio":     "Países Bajos",
        "codigo_pais_iso":   "NL",
        "extranjero":        True,
        "nombre_legal":      "Bitvavo B.V.",
        "nif_custodio":      "NL861859936B01",
        "tipo_id_fiscal":    "VAT_EU",
        "id_type_xsd":       "02",
        "nif_esp":           None,
        "id_otro": {
            "codigo_pais": "NL",
            "id_type":     "02",
            "id":          "NL861859936B01",
        },
        "direccion":         "Herengracht 420-422, 1017 BZ Amsterdam, Países Bajos",
        "confianza_id":      confianza,
        "fuente_id":         "BTW publicado por Bitvavo",
        "requiere_revision": True,
        "activos":           activos,
    }


def _exc_binance(activos):
    return {
        "exchange":          "Binance Holdings Ltd.",
        "exchange_key":      "binance",
        "pais_custodio":     None,
        "codigo_pais_iso":   None,
        "extranjero":        True,
        "nombre_legal":      "Binance Holdings Ltd.",
        "nif_custodio":      None,
        "tipo_id_fiscal":    "DESCONOCIDO",
        "id_type_xsd":       None,
        "nif_esp":           None,
        "id_otro":           None,
        "direccion":         None,
        "confianza_id":      "baja",
        "fuente_id":         "Múltiples entidades legales",
        "requiere_revision": True,
        "activos":           activos,
    }


def _datos(exchanges, total_eur, ejercicio=2024):
    return {
        "modelo":                  "721",
        "ejercicio":               ejercicio,
        "fecha_referencia":        f"31-12-{ejercicio}",
        "potencialmente_obligado": True,
        "informe_orientativo":     True,
        "total_valor_eur":         total_eur,
        "exchanges":               exchanges,
        "advertencias":            [],
    }


def _pendiente_block(datos, nif_declarante):
    from generador_xml_721 import validar_para_xml
    v = validar_para_xml(datos, nif_declarante)
    activos_sin_precio   = []
    exchanges_sin_tax_id = []
    for exc in datos.get("exchanges", []):
        if exc.get("extranjero") is False:
            continue
        if exc.get("nif_custodio") is None:
            exchanges_sin_tax_id.append(exc.get("exchange_key", ""))
        for activo in exc.get("activos", []):
            if activo.get("valor_eur") is None:
                activos_sin_precio.append(activo["activo"])
    completo = (
        not activos_sin_precio and not exchanges_sin_tax_id
        and v.xml_generable and not v.es_borrador
    )
    return {
        "precios_historicos": sorted(set(activos_sin_precio)),
        "tax_id_custodio":    exchanges_sin_tax_id,
        "xml_generable":      v.xml_generable,
        "xml_es_borrador":    v.es_borrador,
        "xml_bloqueantes":    v.bloqueantes,
        "xml_advertencias":   v.advertencias,
        "por_debajo_umbral":  v.por_debajo_umbral,
        "completo":           completo,
    }


def _print_header(titulo, color):
    print(f"\n{BOLD}{color}{'═'*70}{RESET}")
    print(f"{BOLD}{color}  {titulo}{RESET}")
    print(f"{BOLD}{color}{'═'*70}{RESET}")


def _print_pendiente(p):
    print(f"\n  {BOLD}pendiente:{RESET}")
    gen = p["xml_generable"]
    bor = p["xml_es_borrador"]
    estado_color = GREEN if (gen and not bor) else (YELLOW if gen else RED)
    estado_label = "VÁLIDO" if (gen and not bor) else ("BORRADOR" if gen else "BLOQUEADO")
    print(f"    xml_generable:   {estado_color}{gen}{RESET}")
    print(f"    xml_es_borrador: {p['xml_es_borrador']}")
    print(f"    → Estado:        {estado_color}{BOLD}{estado_label}{RESET}")
    if p["xml_bloqueantes"]:
        print(f"    {RED}bloqueantes:{RESET}")
        for b in p["xml_bloqueantes"]:
            print(f"      · {b}")
    if p["xml_advertencias"]:
        print(f"    {YELLOW}advertencias:{RESET}")
        for a in p["xml_advertencias"]:
            print(f"      · {a}")
    if p["precios_historicos"]:
        print(f"    precios pendientes: {p['precios_historicos']}")
    if p["tax_id_custodio"]:
        print(f"    tax_id pendiente:   {p['tax_id_custodio']}")
    print(f"    por_debajo_umbral: {p['por_debajo_umbral']}")
    print(f"    completo:          {BOLD}{GREEN if p['completo'] else RED}{p['completo']}{RESET}")


# ── EJEMPLO 1: BLOQUEADO ───────────────────────────────────────────────────────

_print_header("EJEMPLO 1 — XML BLOQUEADO", RED)
print(f"\n  Situación: usuario ha subido el CSV pero sin NIF, y BNB sin precio.")

datos_bloqueado = _datos(
    exchanges=[
        _exc_bitvavo([
            _activo("BTC",  "0.500000", "42500.00", "Bitcoin"),
            _activo("BNB",  "25.000000", None,       "BNB"),   # sin precio
        ]),
    ],
    total_eur=None,  # no calculable por BNB sin precio
)
pendiente_bloqueado = _pendiente_block(datos_bloqueado, nif_declarante="")

respuesta_bloqueado = {
    "ok":          True,
    "modelo":      "721",
    "ejercicio":   2024,
    "exchange":    "bitvavo",
    "generado_en": "2025-05-20T15:00:00",
    "resultado":   {"...": "(datos del activo, omitidos para brevedad)"},
    "pendiente":   pendiente_bloqueado,
    # sin campo "xml" porque está bloqueado
}

print(f"\n  {BOLD}Respuesta JSON (pendiente):{RESET}")
_print_pendiente(pendiente_bloqueado)
print(f"\n  {RED}→ No se genera campo 'xml' en la respuesta.{RESET}")


# ── EJEMPLO 2: BORRADOR ────────────────────────────────────────────────────────

_print_header("EJEMPLO 2 — XML BORRADOR (Binance sin ID custodio)", YELLOW)
print(f"\n  Situación: todos los precios OK, NIF válido, pero Binance sin tax ID.")

datos_borrador = _datos(
    exchanges=[
        _exc_binance([
            _activo("BTC",  "1.000000", "85000.00", "Bitcoin"),
            _activo("ETH",  "5.000000", "16000.00", "Ethereum"),
        ]),
    ],
    total_eur="101000.00",
)
NIF_DEMO = "12345678Z"
pendiente_borrador = _pendiente_block(datos_borrador, nif_declarante=NIF_DEMO)

print(f"\n  {BOLD}Respuesta JSON (pendiente):{RESET}")
_print_pendiente(pendiente_borrador)

v2 = validar_para_xml(datos_borrador, NIF_DEMO)
xml_borrador, _ = generar_xml_721(datos_borrador, NIF_DEMO, "GARCIA PEREZ JUAN")
print(f"\n  {YELLOW}→ Se genera campo 'xml' con comentario [BORRADOR].{RESET}")
print(f"  Primeras 3 líneas del XML:")
for ln in xml_borrador.split("\n")[:3]:
    print(f"    {ln}")


# ── EJEMPLO 3: VÁLIDO ──────────────────────────────────────────────────────────

_print_header("EJEMPLO 3 — XML VÁLIDO (Bitvavo, ID confirmado)", GREEN)
print(f"\n  Situación: NIF válido, todos los precios, Bitvavo con VAT EU confirmado.")
print(f"  (confianza='media' — solo 'baja' activa borrador para el custodio)")

datos_valido = _datos(
    exchanges=[
        _exc_bitvavo([
            _activo("BTC",  "0.750000", "63750.00", "Bitcoin"),
            _activo("ETH",  "3.000000",  "9600.00", "Ethereum"),
            _activo("USDT", "2500.000000", "2300.00", "Tether USD"),
        ], confianza="media"),
    ],
    total_eur="75650.00",
)
pendiente_valido = _pendiente_block(datos_valido, nif_declarante=NIF_DEMO)

print(f"\n  {BOLD}Respuesta JSON (pendiente):{RESET}")
_print_pendiente(pendiente_valido)

xml_valido, v3 = generar_xml_721(datos_valido, NIF_DEMO, "GARCIA PEREZ JUAN")
print(f"\n  {GREEN}→ XML generado. es_borrador={v3.es_borrador}{RESET}")


# ── XML COMPLETO DEL EJEMPLO 3 ─────────────────────────────────────────────────

_print_header("XML GENERADO — Ejemplo 3 (VÁLIDO, 3 activos Bitvavo)", GREEN)
print(xml_valido)


# ── RESUMEN ────────────────────────────────────────────────────────────────────

_print_header("RESUMEN DE ESTADOS", CYAN)
print(f"""
  {RED}{BOLD}BLOQUEADO{RESET}  → xml_generable=False
             · No se genera campo 'xml' en la respuesta
             · Causas: NIF ausente/inválido | activo sin valor_eur
             · Frontend: mostrar error claro, listar qué falta

  {YELLOW}{BOLD}BORRADOR{RESET}   → xml_generable=True, xml_es_borrador=True
             · Se genera campo 'xml' con comentario [BORRADOR]
             · Causas: custodio sin tax ID | confianza 'baja' | total < 50.000€
             · Frontend: permitir descarga con advertencia visible

  {GREEN}{BOLD}VÁLIDO{RESET}     → xml_generable=True, xml_es_borrador=False
             · Se genera campo 'xml' sin comentario de borrador
             · Frontend: permitir descarga directa, indicar que está listo
""")
