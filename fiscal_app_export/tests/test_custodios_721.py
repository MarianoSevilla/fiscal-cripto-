"""
Tests para custodios_721.py — Fase 3B.2.

Verifica el catálogo de custodios, la función buscar_custodio,
to_dict_xsd, y la integración con generar_datos_modelo_721.
"""

import sys
import os
from datetime import datetime
from decimal import Decimal

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from custodios_721 import (
    CustodioFiscal,
    CUSTODIOS_721,
    buscar_custodio,
    to_dict_xsd,
    _normalizar_key,
    TIPO_ID_NIF_ESP,
    TIPO_ID_VAT_EU,
    TIPO_ID_UEN_SG,
    TIPO_ID_DESCONOCIDO,
    CONFIANZA_ALTA,
    CONFIANZA_MEDIA,
    CONFIANZA_BAJA,
)
from motor_fifo import MotorFIFO
from modelo721 import generar_datos_modelo_721


# ── HELPERS ───────────────────────────────────────────────────────────────────

def _motor_simple(ticker="BTC", qty=1.0, precio=30000.0, año=2024) -> MotorFIFO:
    motor = MotorFIFO()
    motor.registrar_compra(
        fecha=f"{año}-06-01",
        activo=ticker,
        cantidad=qty,
        importe=precio * qty,
        contraparte="EUR",
        fee_activo=ticker,
        fee_cantidad=0.0,
    )
    return motor


# ═══════════════════════════════════════════════════════════════════════════════
# BLOQUE 1 — Estructura del catálogo
# ═══════════════════════════════════════════════════════════════════════════════

class TestCatalogo:

    def test_01_exchanges_principales_presentes(self):
        """Los exchanges principales deben estar en el catálogo."""
        for key in ["binance", "bitvavo", "kraken", "coinbase", "nexo", "cryptocom", "uphold", "bit2me"]:
            assert key in CUSTODIOS_721, f"Falta '{key}' en CUSTODIOS_721"

    def test_02_todas_las_entradas_son_custodio_fiscal(self):
        """Todas las entradas del catálogo son instancias de CustodioFiscal."""
        for key, custodio in CUSTODIOS_721.items():
            assert isinstance(custodio, CustodioFiscal), f"'{key}' no es CustodioFiscal"

    def test_03_exchange_key_coincide_con_clave_dict(self):
        """El campo exchange_key de cada entrada coincide con su clave en el dict."""
        for key, custodio in CUSTODIOS_721.items():
            assert custodio.exchange_key == key, (
                f"Mismatch: dict key='{key}', custodio.exchange_key='{custodio.exchange_key}'"
            )

    def test_04_nombre_legal_no_vacio(self):
        """Todos los custodios tienen nombre_legal no vacío."""
        for key, custodio in CUSTODIOS_721.items():
            assert custodio.nombre_legal and custodio.nombre_legal.strip(), (
                f"'{key}' tiene nombre_legal vacío"
            )

    def test_05_confianza_valores_validos(self):
        """El campo confianza solo puede ser alta/media/baja."""
        validos = {CONFIANZA_ALTA, CONFIANZA_MEDIA, CONFIANZA_BAJA}
        for key, custodio in CUSTODIOS_721.items():
            assert custodio.confianza in validos, (
                f"'{key}' tiene confianza inválida: '{custodio.confianza}'"
            )

    def test_06_fuente_no_vacia(self):
        """Todos los custodios tienen fuente no vacía."""
        for key, custodio in CUSTODIOS_721.items():
            assert custodio.fuente and custodio.fuente.strip(), (
                f"'{key}' tiene fuente vacía"
            )

    def test_07_id_type_xsd_coherente_con_tipo_id(self):
        """id_type_xsd es coherente con tipo_id."""
        for key, custodio in CUSTODIOS_721.items():
            if custodio.tipo_id == TIPO_ID_NIF_ESP:
                assert custodio.id_type_xsd is None, (
                    f"'{key}' NIF_ESP no debe tener id_type_xsd"
                )
            elif custodio.tipo_id == TIPO_ID_VAT_EU:
                assert custodio.id_type_xsd == "02", (
                    f"'{key}' VAT_EU debe tener id_type_xsd='02'"
                )
            elif custodio.tipo_id in (TIPO_ID_UEN_SG,):
                assert custodio.id_type_xsd == "04", (
                    f"'{key}' UEN_SG debe tener id_type_xsd='04'"
                )

    def test_08_si_id_fiscal_confianza_no_baja(self):
        """Si hay id_fiscal, la confianza no debe ser 'baja'."""
        for key, custodio in CUSTODIOS_721.items():
            if custodio.id_fiscal is not None:
                assert custodio.confianza != CONFIANZA_BAJA, (
                    f"'{key}' tiene id_fiscal pero confianza='baja' — inconsistente"
                )

    def test_09_requiere_verificacion_true_si_confianza_baja(self):
        """Si confianza es 'baja', requiere_verificacion siempre debe ser True."""
        for key, custodio in CUSTODIOS_721.items():
            if custodio.confianza == CONFIANZA_BAJA:
                assert custodio.requiere_verificacion is True, (
                    f"'{key}' confianza='baja' pero requiere_verificacion=False"
                )


# ═══════════════════════════════════════════════════════════════════════════════
# BLOQUE 2 — Datos de custodios específicos
# ═══════════════════════════════════════════════════════════════════════════════

class TestDatosCustodios:

    def test_10_bit2me_nif_esp(self):
        """Bit2Me tiene NIF español B42521836."""
        c = CUSTODIOS_721["bit2me"]
        assert c.id_fiscal    == "B42521836"
        assert c.tipo_id      == TIPO_ID_NIF_ESP
        assert c.id_type_xsd  is None
        assert c.codigo_pais_iso == "ES"
        assert c.extranjero   is False
        assert c.confianza    == CONFIANZA_ALTA

    def test_11_bit2me_no_extranjero(self):
        """Bit2Me es española → extranjero=False."""
        c = CUSTODIOS_721["bit2me"]
        assert c.extranjero is False

    def test_12_bitvavo_vat_eu(self):
        """Bitvavo tiene VAT EU NL861859936B01."""
        c = CUSTODIOS_721["bitvavo"]
        assert c.id_fiscal   == "NL861859936B01"
        assert c.tipo_id     == TIPO_ID_VAT_EU
        assert c.id_type_xsd == "02"
        assert c.codigo_pais_iso == "NL"
        assert c.extranjero  is True

    def test_13_bitvavo_confianza_media(self):
        """Bitvavo tiene confianza media."""
        assert CUSTODIOS_721["bitvavo"].confianza == CONFIANZA_MEDIA

    def test_14_cryptocom_uen_sg(self):
        """Crypto.com tiene UEN de Singapur 201935164N."""
        c = CUSTODIOS_721["cryptocom"]
        assert c.id_fiscal   == "201935164N"
        assert c.tipo_id     == TIPO_ID_UEN_SG
        assert c.id_type_xsd == "04"
        assert c.codigo_pais_iso == "SG"

    def test_15_binance_sin_id(self):
        """Binance no tiene id_fiscal confirmado."""
        c = CUSTODIOS_721["binance"]
        assert c.id_fiscal  is None
        assert c.tipo_id    == TIPO_ID_DESCONOCIDO
        assert c.confianza  == CONFIANZA_BAJA
        assert c.requiere_verificacion is True

    def test_16_kraken_sin_id(self):
        """Kraken no tiene id_fiscal confirmado."""
        c = CUSTODIOS_721["kraken"]
        assert c.id_fiscal is None
        assert c.requiere_verificacion is True

    def test_17_exchanges_extranjeros_tienen_pais_o_nota(self):
        """Exchanges extranjeros sin pais ISO deben tener nota explicativa."""
        for key, custodio in CUSTODIOS_721.items():
            if custodio.extranjero and custodio.codigo_pais_iso is None:
                assert custodio.nota, (
                    f"'{key}' extranjero sin codigo_pais_iso debe tener nota"
                )

    def test_18_bit2me_advertencia_modelo_721(self):
        """Bit2Me debe incluir advertencia sobre no-obligación 721."""
        c = CUSTODIOS_721["bit2me"]
        texto_adv = " ".join(c.advertencias)
        assert "Modelo 721" in texto_adv or "721" in texto_adv


# ═══════════════════════════════════════════════════════════════════════════════
# BLOQUE 3 — buscar_custodio
# ═══════════════════════════════════════════════════════════════════════════════

class TestBuscarCustodio:

    def test_19_encuentra_bitvavo(self):
        """buscar_custodio('bitvavo') devuelve el custodio correcto."""
        c = buscar_custodio("bitvavo")
        assert c.exchange_key == "bitvavo"
        assert c.id_fiscal    == "NL861859936B01"

    def test_20_encuentra_bit2me(self):
        """buscar_custodio('bit2me') devuelve Bit2Me con NIF español."""
        c = buscar_custodio("bit2me")
        assert c.id_fiscal == "B42521836"

    def test_21_normaliza_mayusculas(self):
        """buscar_custodio normaliza el input a lowercase."""
        c = buscar_custodio("BITVAVO")
        assert c.exchange_key == "bitvavo"

    def test_22_normaliza_espacios_y_guiones(self):
        """buscar_custodio elimina espacios, guiones y puntos."""
        c1 = buscar_custodio("Bit-2Me")
        c2 = buscar_custodio("bit2me")
        assert c1.id_fiscal == c2.id_fiscal

    def test_23_exchange_desconocido_devuelve_generico(self):
        """Exchange desconocido devuelve CustodioFiscal genérico con confianza baja."""
        c = buscar_custodio("exchange_inexistente_xyz")
        assert c.id_fiscal             is None
        assert c.tipo_id               == TIPO_ID_DESCONOCIDO
        assert c.confianza             == CONFIANZA_BAJA
        assert c.requiere_verificacion is True

    def test_24_exchange_desconocido_tiene_advertencia(self):
        """El custodio genérico incluye al menos una advertencia."""
        c = buscar_custodio("unknownxyz")
        assert len(c.advertencias) >= 1

    def test_25_exchange_desconocido_exchange_key_normalizado(self):
        """El custodio genérico refleja el exchange_key normalizado."""
        c = buscar_custodio("MyExchange")
        assert c.exchange_key == "myexchange"

    def test_26_cryptocom_busqueda_sin_punto(self):
        """cryptocom (sin punto) debe encontrar Crypto.com."""
        c = buscar_custodio("cryptocom")
        assert c.codigo_pais_iso == "SG"


# ═══════════════════════════════════════════════════════════════════════════════
# BLOQUE 4 — to_dict_xsd
# ═══════════════════════════════════════════════════════════════════════════════

class TestToDictXsd:

    def test_27_bit2me_nif_esp_en_nif_esp(self):
        """Bit2Me (NIF español) → nif_esp relleno, id_otro=None."""
        c    = buscar_custodio("bit2me")
        d    = to_dict_xsd(c)
        assert d["nif_esp"] == "B42521836"
        assert d["id_otro"] is None

    def test_28_bitvavo_vat_en_id_otro(self):
        """Bitvavo (VAT EU) → nif_esp=None, id_otro relleno."""
        c = buscar_custodio("bitvavo")
        d = to_dict_xsd(c)
        assert d["nif_esp"] is None
        assert d["id_otro"] is not None
        assert d["id_otro"]["id"]       == "NL861859936B01"
        assert d["id_otro"]["id_type"]  == "02"
        assert d["id_otro"]["codigo_pais"] == "NL"

    def test_29_cryptocom_uen_en_id_otro(self):
        """Crypto.com (UEN SG) → id_otro con id_type='04'."""
        c = buscar_custodio("cryptocom")
        d = to_dict_xsd(c)
        assert d["id_otro"]["id_type"]  == "04"
        assert d["id_otro"]["id"]       == "201935164N"

    def test_30_binance_sin_id_id_otro_none(self):
        """Binance (sin ID) → id_otro=None, nif_esp=None."""
        c = buscar_custodio("binance")
        d = to_dict_xsd(c)
        assert d["nif_esp"]  is None
        assert d["id_otro"]  is None

    def test_31_nombre_legal_presente(self):
        """to_dict_xsd siempre incluye nombre_legal."""
        for key in CUSTODIOS_721:
            d = to_dict_xsd(CUSTODIOS_721[key])
            assert d["nombre_legal"], f"'{key}' sin nombre_legal en XSD dict"

    def test_32_confianza_y_fuente_presentes(self):
        """to_dict_xsd incluye metadatos de trazabilidad."""
        c = buscar_custodio("bitvavo")
        d = to_dict_xsd(c)
        assert d["confianza"] in {CONFIANZA_ALTA, CONFIANZA_MEDIA, CONFIANZA_BAJA}
        assert d["fuente"]

    def test_33_requiere_verificacion_presente(self):
        """to_dict_xsd incluye requiere_verificacion."""
        d = to_dict_xsd(buscar_custodio("kraken"))
        assert d["requiere_verificacion"] is True

    def test_34_result_es_json_serializable(self):
        """Resultado de to_dict_xsd es JSON-serializable."""
        import json
        for key in CUSTODIOS_721:
            d = to_dict_xsd(CUSTODIOS_721[key])
            try:
                json.dumps(d)
            except TypeError as e:
                pytest.fail(f"'{key}' not JSON-serializable: {e}")


# ═══════════════════════════════════════════════════════════════════════════════
# BLOQUE 5 — Integración con generar_datos_modelo_721
# ═══════════════════════════════════════════════════════════════════════════════

class TestIntegracion721:

    def test_35_bitvavo_nif_custodio_relleno(self):
        """generar_datos_modelo_721 para Bitvavo incluye nif_custodio."""
        motor = _motor_simple("BTC", 1.0, 30000.0, 2024)
        datos = generar_datos_modelo_721(motor, "bitvavo", 2024)
        exc   = datos["exchanges"][0]
        assert exc["nif_custodio"]  == "NL861859936B01"
        assert exc["tipo_id_fiscal"] == TIPO_ID_VAT_EU
        assert exc["id_type_xsd"]   == "02"
        assert exc["confianza_id"]  == CONFIANZA_MEDIA

    def test_36_bit2me_nif_custodio_relleno(self):
        """generar_datos_modelo_721 para Bit2Me incluye NIF español."""
        motor = _motor_simple("BTC", 0.5, 30000.0, 2024)
        datos = generar_datos_modelo_721(motor, "bit2me", 2024)
        # Bit2Me puede retornar sin posiciones declarables (extranjero=False)
        # pero si las retorna, el custodio debe estar presente
        assert datos["modelo"] == "721"
        # Si hay exchanges en el resultado
        if datos.get("exchanges"):
            exc = datos["exchanges"][0]
            assert exc["nif_custodio"]   == "B42521836"
            assert exc["tipo_id_fiscal"] == TIPO_ID_NIF_ESP
            assert exc["nif_esp"]        == "B42521836"
            assert exc["id_otro"]        is None

    def test_37_kraken_nif_custodio_none(self):
        """Kraken no tiene id_fiscal confirmado → nif_custodio=None."""
        motor = _motor_simple("ETH", 2.0, 2000.0, 2024)
        datos = generar_datos_modelo_721(motor, "kraken", 2024)
        exc   = datos["exchanges"][0]
        assert exc["nif_custodio"]   is None
        assert exc["tipo_id_fiscal"] == TIPO_ID_DESCONOCIDO
        assert exc["id_type_xsd"]    is None

    def test_38_binance_requiere_revision(self):
        """Binance siempre requiere revisión."""
        motor = _motor_simple("BNB", 10.0, 300.0, 2024)
        datos = generar_datos_modelo_721(motor, "binance", 2024)
        exc   = datos["exchanges"][0]
        assert exc["requiere_revision"] is True

    def test_39_nombre_legal_en_exchange_block(self):
        """El bloque exchange incluye nombre_legal del custodio."""
        motor = _motor_simple("BTC", 1.0, 30000.0, 2024)
        datos = generar_datos_modelo_721(motor, "bitvavo", 2024)
        exc   = datos["exchanges"][0]
        assert "nombre_legal" in exc
        assert exc["nombre_legal"] == "Bitvavo B.V."

    def test_40_id_otro_bitvavo_en_resultado(self):
        """El bloque exchange de Bitvavo incluye id_otro con VAT."""
        motor = _motor_simple("BTC", 1.0, 30000.0, 2024)
        datos = generar_datos_modelo_721(motor, "bitvavo", 2024)
        exc   = datos["exchanges"][0]
        assert exc["id_otro"] is not None
        assert exc["id_otro"]["id"]       == "NL861859936B01"
        assert exc["id_otro"]["id_type"]  == "02"

    def test_41_cryptocom_id_otro_uen(self):
        """Crypto.com: id_otro con UEN de Singapur."""
        motor = _motor_simple("CRO", 1000.0, 0.1, 2024)
        datos = generar_datos_modelo_721(motor, "cryptocom", 2024)
        exc   = datos["exchanges"][0]
        assert exc["id_otro"]["id_type"]  == "04"
        assert exc["id_otro"]["id"]       == "201935164N"

    def test_42_resultado_json_serializable_con_custodio(self):
        """El resultado completo con datos de custodio es JSON-serializable."""
        import json
        motor = _motor_simple("BTC", 1.0, 30000.0, 2024)
        for exchange in ["bitvavo", "binance", "kraken", "cryptocom"]:
            datos = generar_datos_modelo_721(motor, exchange, 2024)
            try:
                json.dumps(datos)
            except TypeError as e:
                pytest.fail(f"'{exchange}' result not JSON-serializable: {e}")

    def test_43_advertencias_custodio_en_resultado(self):
        """Las advertencias del custodio se incluyen en el resultado."""
        motor = _motor_simple("BNB", 5.0, 300.0, 2024)
        datos = generar_datos_modelo_721(motor, "binance", 2024)
        # Las advertencias de Binance sobre múltiples entidades deben aparecer
        texto_adv = " ".join(datos.get("advertencias", []))
        assert "Binance" in texto_adv or "entidades" in texto_adv.lower()

    def test_44_exchange_desconocido_funciona(self):
        """Un exchange no en el catálogo genera resultado sin error."""
        motor = _motor_simple("BTC", 1.0, 30000.0, 2024)
        datos = generar_datos_modelo_721(motor, "exchangedesconocido", 2024)
        assert datos["modelo"] == "721"
        if datos.get("exchanges"):
            exc = datos["exchanges"][0]
            assert exc["nif_custodio"]  is None
            assert exc["requiere_revision"] is True
