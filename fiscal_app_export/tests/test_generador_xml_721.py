"""
Tests para generador_xml_721.py — Fase 3B.3 (XSD-conforme).

Cubre: validación, estados (bloqueado/borrador/válido),
estructura XML según DeclaracionInformativa721.xsd y Declaracion721.xsd.

Cambios frente a la versión anterior:
  · Elemento raíz: Declaracion (namespace ddiiD) en lugar de DeclaracionInformativa721.
  · Cabecera: TipoComunicacion + Modelo + Ejercicio + IDVersionModelo + IDDeclarante.
  · NombreRazon (no NombreRazonSocial) en IDDeclarante e IDPersonaEntidadSalvaguarda.
  · RegistroDeDetalle wrapper con IDRegistroDetalle + RegistroDetalle.
  · Clave al nivel de RegistroDetalle (no dentro de TipoMonedaVirtual).
  · TipoMonedaVirtual solo tiene DenominacionMonedaVirtual + SiglasMonedaVirtual.
  · NumMonedas/ValorMonedas/etc. son hermanos de TipoMonedaVirtual.
  · IDPersonaEntidadSalvaguarda: NombreRazon primero, luego CHOICE NIF|IDOtro.
  · Sin ID de custodio → IDOtro placeholder (IDType=06, ID=PENDIENTE).
  · TipoComunicacion: "A0" (Alta) o "A1" (Modificación) — no "I"/"C"/"S".
"""

import sys
import os
import re
import xml.etree.ElementTree as ET
from decimal import Decimal

import pytest

try:
    import xmlschema as _xmlschema_mod  # type: ignore
    _XMLSCHEMA_DISPONIBLE = True
except ImportError:
    _XMLSCHEMA_DISPONIBLE = False

_SKIP_XSD = pytest.mark.skipif(
    not _XMLSCHEMA_DISPONIBLE,
    reason="xmlschema no instalado (pip install xmlschema)"
)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from generador_xml_721 import (
    ValidacionXML,
    ErrXMLBloqueado,
    UMBRAL_DECLARACION_EUR,
    TIPO_ALTA,
    TIPO_MODIFICACION,
    TIPO_INCIDENCIAS,      # alias de TIPO_ALTA
    TIPO_COMPLEMENTARIA,   # alias de TIPO_MODIFICACION
    validar_para_xml,
    generar_xml_721,
    validar_xml_contra_xsd,
    _nif_valido,
    _fmt_eur,
    _fmt_cantidad,
)


# ── FIXTURES / HELPERS ────────────────────────────────────────────────────────

NIF_OK    = "12345678Z"
NOMBRE_OK = "GARCIA PEREZ JUAN"


def _datos_bitvavo(
    ticker="BTC",
    cantidad="0.5",
    valor_eur="42500.00",
    ejercicio=2024,
    nif_custodio="NL861859936B01",
) -> dict:
    """Datos 721 mínimos de Bitvavo con precio ya resuelto."""
    return {
        "modelo":                  "721",
        "ejercicio":               ejercicio,
        "fecha_referencia":        f"31-12-{ejercicio}",
        "potencialmente_obligado": True,
        "informe_orientativo":     True,
        "total_valor_eur":         valor_eur,
        "exchanges": [{
            "exchange":          "Bitvavo B.V.",
            "exchange_key":      "bitvavo",
            "pais_custodio":     "Países Bajos",
            "codigo_pais_iso":   "NL",
            "extranjero":        True,
            "nombre_legal":      "Bitvavo B.V.",
            "nif_custodio":      nif_custodio,
            "tipo_id_fiscal":    "VAT_EU",
            "id_type_xsd":       "02",
            "nif_esp":           None,
            "id_otro": {
                "codigo_pais": "NL",
                "id_type":     "02",
                "id":          nif_custodio,
            } if nif_custodio else None,
            "direccion":         "Herengracht 420-422, 1017 BZ Amsterdam",
            "confianza_id":      "media",
            "fuente_id":         "Publicado por Bitvavo",
            "requiere_revision": True,
            "activos": [{
                "activo":                ticker,
                "denominacion":          "Bitcoin",
                "siglas":                "BTC",
                "cantidad":              cantidad,
                "valor_eur":             valor_eur,
                "origen_valor":          "O",
                "coste_base_fifo":       "20000.00",
                "clave":                 "T",
                "origen_moneda_virtual": "A",
                "fecha_referencia":      f"31-12-{ejercicio}",
                "requiere_revision":     True,
                "advertencias":          [],
            }],
        }],
        "advertencias": [],
    }


def _datos_sin_precio(ticker="XYZ") -> dict:
    """Datos 721 con activo sin precio (valor_eur=None)."""
    datos = _datos_bitvavo(ticker=ticker, valor_eur=None)
    datos["exchanges"][0]["activos"][0]["valor_eur"] = None
    datos["total_valor_eur"] = None
    return datos


def _datos_sin_custodio_id() -> dict:
    """Datos 721 con custodio sin id_fiscal (Binance-like)."""
    datos = _datos_bitvavo(nif_custodio=None)
    datos["exchanges"][0]["nif_custodio"]  = None
    datos["exchanges"][0]["id_otro"]       = None
    datos["exchanges"][0]["confianza_id"]  = "baja"
    datos["exchanges"][0]["codigo_pais_iso"] = None
    return datos


def _datos_espanola() -> dict:
    """Datos 721 de entidad española (bit2me — no sujeta)."""
    return {
        "modelo": "721", "ejercicio": 2024, "fecha_referencia": "31-12-2024",
        "potencialmente_obligado": False, "informe_orientativo": True,
        "total_valor_eur": "5000.00",
        "exchanges": [{
            "exchange": "Bitnovo Solutions S.L.", "exchange_key": "bit2me",
            "pais_custodio": "España", "codigo_pais_iso": "ES",
            "extranjero": False,
            "nombre_legal": "Bitnovo Solutions S.L.",
            "nif_custodio": "B42521836", "tipo_id_fiscal": "NIF_ESP",
            "id_type_xsd": None, "nif_esp": "B42521836", "id_otro": None,
            "direccion": None, "confianza_id": "alta", "fuente_id": "RM",
            "requiere_revision": False,
            "activos": [{
                "activo": "BTC", "denominacion": "Bitcoin", "siglas": "BTC",
                "cantidad": "0.1", "valor_eur": "5000.00", "origen_valor": "O",
                "coste_base_fifo": "3000.00", "clave": "T",
                "origen_moneda_virtual": "A", "fecha_referencia": "31-12-2024",
                "requiere_revision": False, "advertencias": [],
            }],
        }],
        "advertencias": [],
    }


def _strip_ns(elem: ET.Element) -> None:
    """Elimina namespaces de todos los tags del árbol (en su lugar, recursivo)."""
    elem.tag = re.sub(r'\{[^}]+\}', '', elem.tag)
    for child in elem:
        _strip_ns(child)


def _parse_xml(xml_str: str) -> ET.Element:
    """
    Parsea el XML devuelto quitando comentarios y normalizando namespaces.

    Después del parse, todos los tags son simples (sin prefijo ni {ns}) para
    que las rutas de búsqueda tipo root.find("Cabecera/IDDeclarante/NIF")
    funcionen sin tener que incluir la URI del namespace.
    """
    limpio = re.sub(r'<!--.*?-->', '', xml_str, flags=re.DOTALL)
    limpio = re.sub(r'<\?xml[^?]*\?>', '', limpio).strip()
    root = ET.fromstring(limpio)
    _strip_ns(root)
    return root


# ═══════════════════════════════════════════════════════════════════════════════
# BLOQUE 1 — _nif_valido
# ═══════════════════════════════════════════════════════════════════════════════

class TestNifValido:

    def test_01_nif_valido_formato_correcto(self):
        """NIF de 8 dígitos + letra es válido."""
        assert _nif_valido("12345678Z") is True

    def test_02_nie_valido(self):
        """NIE con X/Y/Z + 7 dígitos + letra es válido."""
        assert _nif_valido("X1234567L") is True
        assert _nif_valido("Y9876543T") is True

    def test_03_cif_valido(self):
        """CIF con letra + 7 dígitos + letra es válido."""
        assert _nif_valido("B42521836") is True

    def test_04_demasiado_corto_invalido(self):
        assert _nif_valido("1234567Z") is False   # 8 chars, falta 1

    def test_05_demasiado_largo_invalido(self):
        assert _nif_valido("123456789ZZ") is False

    def test_06_vacio_invalido(self):
        assert _nif_valido("") is False

    def test_07_solo_letras_invalido(self):
        assert _nif_valido("ABCDEFGHZ") is False

    def test_08_minusculas_aceptadas(self):
        """La validación debe aceptar minúsculas normalizando a uppercase."""
        assert _nif_valido("12345678z") is True


# ═══════════════════════════════════════════════════════════════════════════════
# BLOQUE 2 — validar_para_xml
# ═══════════════════════════════════════════════════════════════════════════════

class TestValidarParaXml:

    def test_09_bloqueado_sin_nif(self):
        """Sin NIF → xml_generable=False."""
        v = validar_para_xml(_datos_bitvavo(), nif_declarante=None)
        assert v.xml_generable is False
        assert any("NIF" in b for b in v.bloqueantes)

    def test_10_bloqueado_nif_vacio(self):
        """NIF vacío → xml_generable=False."""
        v = validar_para_xml(_datos_bitvavo(), nif_declarante="")
        assert v.xml_generable is False

    def test_11_bloqueado_nif_formato_invalido(self):
        """NIF con formato inválido → xml_generable=False con mensaje claro."""
        v = validar_para_xml(_datos_bitvavo(), nif_declarante="INVALIDO")
        assert v.xml_generable is False
        assert any("formato" in b.lower() for b in v.bloqueantes)

    def test_12_bloqueado_sin_precio(self):
        """Activo sin precio → xml_generable=False."""
        v = validar_para_xml(_datos_sin_precio(), nif_declarante=NIF_OK)
        assert v.xml_generable is False
        assert any("ValorMonedas" in b or "precio" in b.lower() for b in v.bloqueantes)

    def test_13_bloqueado_sin_precio_menciona_ticker(self):
        """El mensaje de bloqueo menciona el ticker sin precio."""
        v = validar_para_xml(_datos_sin_precio("ETH"), nif_declarante=NIF_OK)
        assert any("ETH" in b for b in v.bloqueantes)

    def test_14_generable_datos_completos(self):
        """Datos completos y NIF válido → xml_generable=True."""
        v = validar_para_xml(_datos_bitvavo(), nif_declarante=NIF_OK)
        assert v.xml_generable is True

    def test_15_borrador_sin_id_custodio(self):
        """Sin id_fiscal del custodio → es_borrador=True."""
        v = validar_para_xml(_datos_sin_custodio_id(), nif_declarante=NIF_OK)
        assert v.xml_generable is True
        assert v.es_borrador   is True
        assert any("IDPersonaEntidadSalvaguarda" in a or "identificador" in a.lower()
                   for a in v.advertencias)

    def test_16_borrador_confianza_baja(self):
        """Confianza baja en custodio → es_borrador=True."""
        v = validar_para_xml(_datos_sin_custodio_id(), nif_declarante=NIF_OK)
        assert v.es_borrador is True
        assert any("confianza" in a.lower() or "baja" in a.lower()
                   for a in v.advertencias)

    def test_17_borrador_por_debajo_umbral(self):
        """Valor total < 50.000 EUR → es_borrador=True + por_debajo_umbral=True."""
        datos = _datos_bitvavo(valor_eur="25000.00")
        datos["total_valor_eur"] = "25000.00"
        v = validar_para_xml(datos, nif_declarante=NIF_OK)
        assert v.por_debajo_umbral is True
        assert v.es_borrador       is True
        assert any("50.000" in a or "50000" in a for a in v.advertencias)

    def test_18_valido_sin_borrador(self):
        """Bitvavo con confianza_id='alta' y valor > 50K → válido sin borrador."""
        datos = _datos_bitvavo(valor_eur="85000.00")
        datos["total_valor_eur"]                     = "85000.00"
        datos["exchanges"][0]["confianza_id"]        = "alta"
        datos["exchanges"][0]["requiere_revision"]   = False
        v = validar_para_xml(datos, nif_declarante=NIF_OK)
        assert v.xml_generable is True
        assert v.es_borrador   is False
        assert v.bloqueantes   == []
        assert v.advertencias  == []

    def test_19_entidad_espanola_no_bloquea_por_precio(self):
        """Activos de entidad española (extranjero=False) no bloquean por precio."""
        datos = _datos_espanola()
        datos["exchanges"][0]["activos"][0]["valor_eur"] = None
        v = validar_para_xml(datos, nif_declarante=NIF_OK)
        assert not any("ValorMonedas" in b for b in v.bloqueantes)

    def test_20_multiples_bloqueantes(self):
        """NIF inválido Y precio pendiente → ambos bloqueantes presentes."""
        v = validar_para_xml(_datos_sin_precio(), nif_declarante="MALFMT")
        assert len(v.bloqueantes) == 2

    def test_21_validacion_devuelve_validacion_xml(self):
        """validar_para_xml siempre devuelve instancia ValidacionXML."""
        v = validar_para_xml(_datos_bitvavo(), nif_declarante=NIF_OK)
        assert isinstance(v, ValidacionXML)


# ═══════════════════════════════════════════════════════════════════════════════
# BLOQUE 3 — generar_xml_721: errores y estados
# ═══════════════════════════════════════════════════════════════════════════════

class TestGenerarXmlEstados:

    def test_22_raises_bloqueado_sin_nif(self):
        """Sin NIF → ErrXMLBloqueado."""
        with pytest.raises(ErrXMLBloqueado) as exc_info:
            generar_xml_721(_datos_bitvavo(), "", NOMBRE_OK)
        assert len(exc_info.value.bloqueantes) > 0

    def test_23_raises_bloqueado_sin_precio(self):
        """Sin precio → ErrXMLBloqueado."""
        with pytest.raises(ErrXMLBloqueado):
            generar_xml_721(_datos_sin_precio(), NIF_OK, NOMBRE_OK)

    def test_24_raises_valor_error_tipo_invalido(self):
        """tipo_comunicacion inválido → ValueError."""
        with pytest.raises(ValueError, match="inválido"):
            generar_xml_721(_datos_bitvavo(), NIF_OK, NOMBRE_OK,
                            tipo_comunicacion="X")

    def test_25_raises_valor_error_nombre_vacio(self):
        """nombre_declarante vacío → ValueError."""
        with pytest.raises(ValueError, match="vacío"):
            generar_xml_721(_datos_bitvavo(), NIF_OK, "")

    def test_26_genera_xml_valido_datos_completos(self):
        """Datos completos y válidos → genera XML sin excepción."""
        datos = _datos_bitvavo(valor_eur="85000.00")
        datos["total_valor_eur"]              = "85000.00"
        datos["exchanges"][0]["confianza_id"] = "alta"
        xml_str, v = generar_xml_721(datos, NIF_OK, NOMBRE_OK)
        assert isinstance(xml_str, str)
        assert len(xml_str) > 0
        assert v.xml_generable is True

    def test_27_genera_xml_borrador_sin_id_custodio(self):
        """Sin id_fiscal → genera XML con es_borrador=True y comentario BORRADOR."""
        xml_str, v = generar_xml_721(_datos_sin_custodio_id(), NIF_OK, NOMBRE_OK)
        assert v.es_borrador is True
        assert "[BORRADOR]" in xml_str

    def test_28_forzar_borrador(self):
        """forzar_borrador=True marca el XML aunque los datos sean válidos."""
        datos = _datos_bitvavo(valor_eur="85000.00")
        datos["total_valor_eur"]              = "85000.00"
        datos["exchanges"][0]["confianza_id"] = "alta"
        xml_str, v = generar_xml_721(datos, NIF_OK, NOMBRE_OK, forzar_borrador=True)
        assert "[BORRADOR]" in xml_str

    def test_29_xml_valido_no_tiene_comentario_borrador(self):
        """XML válido (no borrador) no tiene comentario BORRADOR."""
        datos = _datos_bitvavo(valor_eur="85000.00")
        datos["total_valor_eur"]              = "85000.00"
        datos["exchanges"][0]["confianza_id"] = "alta"
        xml_str, v = generar_xml_721(datos, NIF_OK, NOMBRE_OK)
        assert v.es_borrador   is False
        assert "[BORRADOR]" not in xml_str

    def test_30_devuelve_tuple_xml_y_validacion(self):
        """generar_xml_721 devuelve tuple (str, ValidacionXML)."""
        resultado = generar_xml_721(_datos_bitvavo(), NIF_OK, NOMBRE_OK)
        xml_str, v = resultado
        assert isinstance(xml_str, str)
        assert isinstance(v, ValidacionXML)


# ═══════════════════════════════════════════════════════════════════════════════
# BLOQUE 4 — Estructura XML conforme al XSD oficial
# ═══════════════════════════════════════════════════════════════════════════════

class TestEstructuraXml:
    """
    Verifica que el XML generado sigue la estructura exigida por
    DeclaracionInformativa721.xsd y Declaracion721.xsd de la AEAT.

    Los tests usan _parse_xml() que elimina los namespaces de los tags,
    permitiendo rutas simples tipo root.find("Cabecera/IDDeclarante/NIF").
    """

    def _xml(self, datos=None, nif=NIF_OK, nombre=NOMBRE_OK) -> ET.Element:
        if datos is None:
            datos = _datos_bitvavo(valor_eur="85000.00")
            datos["total_valor_eur"]              = "85000.00"
            datos["exchanges"][0]["confianza_id"] = "alta"
        xml_str, _ = generar_xml_721(datos, nif, nombre)
        return _parse_xml(xml_str)

    # ── Raíz y Cabecera ───────────────────────────────────────────────────────

    def test_31_raiz_es_declaracion(self):
        """Elemento raíz es 'Declaracion' (namespace ddiiD)."""
        root = self._xml()
        assert root.tag == "Declaracion"

    def test_32_cabecera_ejercicio(self):
        """Cabecera/Ejercicio contiene el año del ejercicio."""
        root = self._xml()
        ej_el = root.find("Cabecera/Ejercicio")
        assert ej_el is not None
        assert ej_el.text == "2024"

    def test_33_cabecera_tipo_comunicacion_alta(self):
        """Cabecera/TipoComunicacion es 'A0' por defecto (Alta)."""
        root = self._xml()
        tc_el = root.find("Cabecera/TipoComunicacion")
        assert tc_el is not None
        assert tc_el.text == "A0"

    def test_34_cabecera_nif_declarante(self):
        """Cabecera/IDDeclarante/NIF coincide con el input (uppercase)."""
        root   = self._xml(nif="12345678z")
        nif_el = root.find("Cabecera/IDDeclarante/NIF")
        assert nif_el is not None
        assert nif_el.text == "12345678Z"

    def test_35_cabecera_nombre_declarante(self):
        """Cabecera/IDDeclarante/NombreRazon coincide con el input."""
        root      = self._xml()
        nombre_el = root.find("Cabecera/IDDeclarante/NombreRazon")
        assert nombre_el is not None
        assert nombre_el.text == NOMBRE_OK

    def test_36_cabecera_modelo_721(self):
        """Cabecera/Modelo es '721'."""
        root = self._xml()
        modelo_el = root.find("Cabecera/Modelo")
        assert modelo_el is not None
        assert modelo_el.text == "721"

    def test_37_cabecera_version_modelo(self):
        """Cabecera/IDVersionModelo es '1.0'."""
        root  = self._xml()
        ver_el = root.find("Cabecera/IDVersionModelo")
        assert ver_el is not None
        assert ver_el.text == "1.0"

    # ── RegistroDeDetalle ─────────────────────────────────────────────────────

    def test_38_registro_de_detalle_presente(self):
        """Existe al menos un elemento RegistroDeDetalle hijo de la raíz."""
        root = self._xml()
        registros = root.findall("RegistroDeDetalle")
        assert len(registros) >= 1

    def test_39_id_registro_detalle_secuencial(self):
        """IDRegistroDetalle es '1' para el primer registro."""
        root   = self._xml()
        id_el  = root.find("RegistroDeDetalle/IDRegistroDetalle")
        assert id_el is not None
        assert id_el.text == "1"

    def test_40_id_otro_bitvavo_en_registro(self):
        """RegistroDeDetalle/RegistroDetalle/IDPersonaEntidadSalvaguarda tiene IDOtro con VAT de Bitvavo."""
        root    = self._xml()
        id_el   = root.find(
            "RegistroDeDetalle/RegistroDetalle/IDPersonaEntidadSalvaguarda"
        )
        assert id_el is not None
        id_otro = id_el.find("IDOtro")
        assert id_otro is not None
        assert id_otro.find("IDType").text     == "02"
        assert id_otro.find("ID").text         == "NL861859936B01"
        assert id_otro.find("CodigoPais").text == "NL"

    def test_41_nombre_razon_en_id_persona(self):
        """IDPersonaEntidadSalvaguarda tiene NombreRazon (no NombreRazonSocial) con el nombre del custodio."""
        root      = self._xml()
        nombre_el = root.find(
            "RegistroDeDetalle/RegistroDetalle"
            "/IDPersonaEntidadSalvaguarda/NombreRazon"
        )
        assert nombre_el is not None
        assert "Bitvavo" in nombre_el.text

    def test_42_tipo_moneda_virtual_solo_dos_campos(self):
        """TipoMonedaVirtual contiene únicamente DenominacionMonedaVirtual y SiglasMonedaVirtual."""
        root = self._xml()
        tm   = root.find(
            "RegistroDeDetalle/RegistroDetalle/TipoMonedaVirtual"
        )
        assert tm is not None
        hijos = [child.tag for child in tm]
        assert set(hijos) == {"DenominacionMonedaVirtual", "SiglasMonedaVirtual"}

    def test_43_valor_monedas_es_hermano_de_tipo_moneda(self):
        """ValorMonedas es hijo directo de RegistroDetalle (hermano de TipoMonedaVirtual)."""
        root    = self._xml()
        reg     = root.find("RegistroDeDetalle/RegistroDetalle")
        assert reg is not None
        valor_el = reg.find("ValorMonedas")
        assert valor_el is not None
        assert Decimal(valor_el.text) == Decimal("85000.00")

    def test_44_num_monedas_seis_decimales(self):
        """NumMonedas (hermano de TipoMonedaVirtual) tiene 6 decimales."""
        root    = self._xml()
        reg     = root.find("RegistroDeDetalle/RegistroDetalle")
        num_el  = reg.find("NumMonedas")
        assert num_el is not None
        assert "." in num_el.text
        decimals = num_el.text.split(".")[1]
        assert len(decimals) == 6

    def test_45_entidad_espanola_no_genera_registro(self):
        """Entidades con extranjero=False no generan RegistroDeDetalle.

        LOTE 1 (validación XSD runtime): una declaración solo con entidades
        españolas no tiene registros y el XSD AEAT exige al menos uno, así
        que ya no se entrega un XML inválido (solo cabecera) — se bloquea
        con ErrXMLBloqueado y mensaje explicativo.
        """
        datos = _datos_espanola()
        datos["exchanges"][0]["activos"][0]["valor_eur"] = "5000.00"
        datos["total_valor_eur"] = "5000.00"
        with pytest.raises(ErrXMLBloqueado) as exc_info:
            generar_xml_721(datos, NIF_OK, NOMBRE_OK)
        assert "custodios extranjeros" in str(exc_info.value)

    def test_46_sin_id_custodio_placeholder_en_id_otro(self):
        """
        Si el custodio no tiene ID, IDPersonaEntidadSalvaguarda debe tener
        IDOtro con IDType=06 e ID=PENDIENTE (exigido por <choice> del XSD).
        """
        xml_str, _ = generar_xml_721(_datos_sin_custodio_id(), NIF_OK, NOMBRE_OK)
        root = _parse_xml(xml_str)
        id_el   = root.find(
            "RegistroDeDetalle/RegistroDetalle/IDPersonaEntidadSalvaguarda"
        )
        assert id_el is not None
        id_otro = id_el.find("IDOtro")
        assert id_otro is not None, "IDOtro debe existir (con placeholder) cuando no hay ID de custodio"
        assert id_otro.find("IDType").text == "06"
        assert id_otro.find("ID").text     == "PENDIENTE"
        # NIF no debe estar (no es entidad española)
        assert id_el.find("NIF") is None
        # NombreRazon sí debe estar
        assert id_el.find("NombreRazon") is not None

    def test_47_xml_bien_formado_parseable(self):
        """El XML generado siempre es parseable por ET sin importar el estado."""
        xml_str, _ = generar_xml_721(_datos_bitvavo(), NIF_OK, NOMBRE_OK)
        root = _parse_xml(xml_str)
        assert root is not None

    def test_48_tipo_comunicacion_modificacion(self):
        """tipo_comunicacion='A1' aparece en Cabecera/TipoComunicacion."""
        datos = _datos_bitvavo(valor_eur="85000.00")
        datos["total_valor_eur"]              = "85000.00"
        datos["exchanges"][0]["confianza_id"] = "alta"
        xml_str, _ = generar_xml_721(
            datos, NIF_OK, NOMBRE_OK, tipo_comunicacion=TIPO_MODIFICACION
        )
        root  = _parse_xml(xml_str)
        tc_el = root.find("Cabecera/TipoComunicacion")
        assert tc_el.text == "A1"

    def test_49_multiples_activos_multiples_registros(self):
        """Dos activos en el mismo exchange generan dos RegistroDeDetalle con IDs 1 y 2."""
        datos = _datos_bitvavo(valor_eur="85000.00")
        datos["total_valor_eur"]              = "117000.00"
        datos["exchanges"][0]["confianza_id"] = "alta"
        datos["exchanges"][0]["activos"].append({
            "activo": "ETH", "denominacion": "Ethereum", "siglas": "ETH",
            "cantidad": "10.0", "valor_eur": "32000.00", "origen_valor": "O",
            "coste_base_fifo": "15000.00", "clave": "T",
            "origen_moneda_virtual": "A", "fecha_referencia": "31-12-2024",
            "requiere_revision": True, "advertencias": [],
        })
        xml_str, _ = generar_xml_721(datos, NIF_OK, NOMBRE_OK)
        root       = _parse_xml(xml_str)
        registros  = root.findall("RegistroDeDetalle")
        assert len(registros) == 2
        # IDRegistroDetalle secuencial
        assert registros[0].find("IDRegistroDetalle").text == "1"
        assert registros[1].find("IDRegistroDetalle").text == "2"

    def test_50_xml_declaracion_utf8_presente(self):
        """El XML generado comienza con <?xml version="1.0" encoding="UTF-8"?>."""
        xml_str, _ = generar_xml_721(_datos_bitvavo(), NIF_OK, NOMBRE_OK)
        assert xml_str.strip().startswith("<?xml")
        assert "UTF-8" in xml_str or "utf-8" in xml_str.lower()

    # ── Tests adicionales para estructura XSD ────────────────────────────────

    def test_51_clave_en_registro_detalle_no_en_tipo_moneda(self):
        """Clave debe ser hijo directo de RegistroDetalle, NO de TipoMonedaVirtual."""
        root = self._xml()
        reg  = root.find("RegistroDeDetalle/RegistroDetalle")
        # Clave en RegistroDetalle
        assert reg.find("Clave") is not None
        # NO debe haber Clave dentro de TipoMonedaVirtual
        tm = reg.find("TipoMonedaVirtual")
        assert tm.find("Clave") is None

    def test_52_domicilio_con_codigo_pais(self):
        """DomicilioEntidadSalvaguarda incluye CodigoPais cuando el custodio tiene país."""
        root   = self._xml()
        dom_el = root.find(
            "RegistroDeDetalle/RegistroDetalle"
            "/IDPersonaEntidadSalvaguarda/DomicilioEntidadSalvaguarda"
        )
        assert dom_el is not None
        pais_el = dom_el.find("CodigoPais")
        assert pais_el is not None
        assert pais_el.text == "NL"

    def test_53_sin_pais_no_genera_domicilio(self):
        """Sin CodigoPais en el custodio, DomicilioEntidadSalvaguarda no se genera."""
        xml_str, _ = generar_xml_721(_datos_sin_custodio_id(), NIF_OK, NOMBRE_OK)
        root = _parse_xml(xml_str)
        dom_el = root.find(
            "RegistroDeDetalle/RegistroDetalle"
            "/IDPersonaEntidadSalvaguarda/DomicilioEntidadSalvaguarda"
        )
        assert dom_el is None

    def test_54_nombre_razon_es_primer_hijo_de_id_persona(self):
        """NombreRazon debe ser el PRIMER hijo de IDPersonaEntidadSalvaguarda."""
        root  = self._xml()
        id_el = root.find(
            "RegistroDeDetalle/RegistroDetalle/IDPersonaEntidadSalvaguarda"
        )
        primer_hijo = list(id_el)[0]
        assert primer_hijo.tag == "NombreRazon"

    def test_55_entidad_espanola_genera_nif_en_id_persona(self):
        """Para entidad española, IDPersonaEntidadSalvaguarda usa <NIF> (no IDOtro)."""
        # Creamos datos con exchange español
        datos_esp = _datos_espanola()
        # Añadir también un exchange extranjero para que haya algo que declarar
        datos_bitvavo = _datos_bitvavo(valor_eur="85000.00")
        datos_bitvavo["exchanges"][0]["confianza_id"] = "alta"
        # Usar datos_bitvavo para generar XML (entidad española no aparece en XML)
        xml_str, _ = generar_xml_721(
            datos_bitvavo, NIF_OK, NOMBRE_OK
        )
        root = _parse_xml(xml_str)
        id_el = root.find(
            "RegistroDeDetalle/RegistroDetalle/IDPersonaEntidadSalvaguarda"
        )
        # Bitvavo es extranjero, debe tener IDOtro no NIF
        assert id_el.find("IDOtro") is not None
        assert id_el.find("NIF")    is None

    def test_56_alias_tipo_incidencias_es_a0(self):
        """TIPO_INCIDENCIAS es alias de TIPO_ALTA ('A0') por compatibilidad."""
        assert TIPO_INCIDENCIAS    == "A0"
        assert TIPO_COMPLEMENTARIA == "A1"

    def test_57_compat_valores_viejos_i_c(self):
        """tipo_comunicacion='I' y 'C' (valores anteriores al XSD) se aceptan por compatibilidad."""
        datos = _datos_bitvavo(valor_eur="85000.00")
        datos["total_valor_eur"]              = "85000.00"
        datos["exchanges"][0]["confianza_id"] = "alta"
        # 'I' → TIPO_ALTA → 'A0'
        xml_str, _ = generar_xml_721(datos, NIF_OK, NOMBRE_OK, tipo_comunicacion="I")
        root = _parse_xml(xml_str)
        assert root.find("Cabecera/TipoComunicacion").text == "A0"
        # 'C' → TIPO_MODIFICACION → 'A1'
        xml_str2, _ = generar_xml_721(datos, NIF_OK, NOMBRE_OK, tipo_comunicacion="C")
        root2 = _parse_xml(xml_str2)
        assert root2.find("Cabecera/TipoComunicacion").text == "A1"

    def test_58_origen_moneda_virtual_en_registro(self):
        """OrigenMonedaVirtual (A/M/C) aparece como hermano de TipoMonedaVirtual."""
        root = self._xml()
        reg  = root.find("RegistroDeDetalle/RegistroDetalle")
        omv  = reg.find("OrigenMonedaVirtual")
        assert omv is not None
        assert omv.text in {"A", "M", "C"}

    def test_59_saldo_monedas_iguales_a_num_monedas(self):
        """SaldoMonedasVirtuales es igual a NumMonedas para posición a 31/12."""
        root = self._xml()
        reg  = root.find("RegistroDeDetalle/RegistroDetalle")
        assert reg.find("NumMonedas").text == reg.find("SaldoMonedasVirtuales").text

    def test_60_xml_tiene_namespaces_ddii_y_ddiid(self):
        """El XML generado incluye los namespaces ddii y ddiiD de la AEAT."""
        datos = _datos_bitvavo(valor_eur="85000.00")
        datos["total_valor_eur"]              = "85000.00"
        datos["exchanges"][0]["confianza_id"] = "alta"
        xml_str, _ = generar_xml_721(datos, NIF_OK, NOMBRE_OK)
        assert "agenciatributaria.gob.es" in xml_str
        assert "DeclaracionInformativa.xsd" in xml_str
        assert "Declaracion.xsd" in xml_str


# ═══════════════════════════════════════════════════════════════════════════════
# BLOQUE 5 — Validación XSD oficial AEAT (requiere xmlschema)
# ═══════════════════════════════════════════════════════════════════════════════

@_SKIP_XSD
class TestValidacionXSD:
    """
    Valida los XML generados contra los XSD oficiales de la AEAT:
      · Declaracion721.xsd  (importa DeclaracionInformativa721.xsd)

    Estos tests requieren el paquete 'xmlschema' (pip install xmlschema)
    y los ficheros .xsd en fiscal_app_export/.
    """

    def _xml_valido(self) -> str:
        """Genera un XML en estado VÁLIDO (sin errores de validación esperados)."""
        datos = _datos_bitvavo(valor_eur="85000.00")
        datos["total_valor_eur"]              = "85000.00"
        datos["exchanges"][0]["confianza_id"] = "alta"
        xml_str, _ = generar_xml_721(datos, NIF_OK, NOMBRE_OK)
        return xml_str

    def _xml_borrador(self) -> str:
        """Genera un XML en estado BORRADOR (custodio sin ID, placeholder)."""
        datos = _datos_bitvavo(valor_eur="85000.00")
        datos["total_valor_eur"]               = "85000.00"
        datos["exchanges"][0]["nif_custodio"]  = None
        datos["exchanges"][0]["id_otro"]       = None
        datos["exchanges"][0]["confianza_id"]  = "baja"
        datos["exchanges"][0]["codigo_pais_iso"] = None
        xml_str, _ = generar_xml_721(datos, NIF_OK, NOMBRE_OK)
        return xml_str

    def test_61_xml_valido_pasa_xsd(self):
        """XML en estado VÁLIDO debe pasar la validación XSD oficial AEAT."""
        valido, errores = validar_xml_contra_xsd(self._xml_valido())
        assert valido is True, f"Errores XSD inesperados: {errores}"
        assert errores == []

    def test_62_xml_borrador_pasa_xsd(self):
        """
        XML en estado BORRADOR (con IDOtro placeholder) también debe ser
        XML bien formado y pasar el XSD, ya que el <choice> exige un elemento.
        """
        valido, errores = validar_xml_contra_xsd(self._xml_borrador())
        assert valido is True, f"Errores XSD en BORRADOR: {errores}"

    def test_63_validar_devuelve_tuple(self):
        """validar_xml_contra_xsd siempre devuelve (bool, list)."""
        resultado = validar_xml_contra_xsd(self._xml_valido())
        assert isinstance(resultado, tuple)
        assert isinstance(resultado[0], bool)
        assert isinstance(resultado[1], list)

    def test_64_xml_multiple_registros_pasa_xsd(self):
        """XML con 3 activos (3 RegistroDeDetalle) pasa el XSD."""
        datos = _datos_bitvavo(valor_eur="85000.00")
        datos["total_valor_eur"]              = "170000.00"
        datos["exchanges"][0]["confianza_id"] = "alta"
        datos["exchanges"][0]["activos"] += [
            {
                "activo": "ETH", "denominacion": "Ethereum", "siglas": "ETH",
                "cantidad": "5.0", "valor_eur": "16000.00", "origen_valor": "O",
                "coste_base_fifo": "8000.00", "clave": "T",
                "origen_moneda_virtual": "A", "fecha_referencia": "31-12-2024",
                "requiere_revision": False, "advertencias": [],
            },
            {
                "activo": "USDT", "denominacion": "Tether USD", "siglas": "USDT",
                "cantidad": "5000.0", "valor_eur": "4600.00", "origen_valor": "O",
                "coste_base_fifo": "5000.00", "clave": "T",
                "origen_moneda_virtual": "A", "fecha_referencia": "31-12-2024",
                "requiere_revision": False, "advertencias": [],
            },
        ]
        xml_str, _ = generar_xml_721(datos, NIF_OK, NOMBRE_OK)
        valido, errores = validar_xml_contra_xsd(xml_str)
        assert valido is True, f"Errores XSD con múltiples registros: {errores}"

    def test_65_xml_tipo_comunicacion_a1_pasa_xsd(self):
        """XML con TipoComunicacion='A1' (Modificación) pasa el XSD."""
        datos = _datos_bitvavo(valor_eur="85000.00")
        datos["total_valor_eur"]              = "85000.00"
        datos["exchanges"][0]["confianza_id"] = "alta"
        xml_str, _ = generar_xml_721(
            datos, NIF_OK, NOMBRE_OK, tipo_comunicacion=TIPO_MODIFICACION
        )
        valido, errores = validar_xml_contra_xsd(xml_str)
        assert valido is True, f"Errores XSD con A1: {errores}"
