"""
Catálogo de custodios para el Modelo 721.

FASE 3B.2 — Datos fiscales de exchanges/custodios.

Proporciona los datos del IDPersonaEntidadSalvaguarda del XSD AEAT:
  - Nombre legal
  - País (CodigoPais)
  - Identificador fiscal (NIF o IDOtro: CodigoPais + IDType + ID)
  - Dirección (Domicilio, opcional en el XSD)
  - Nivel de confianza y fuente del dato

Referencia XSD:
  - IDPersonaEntidadSalvaguarda en DeclaracionInformativa721.xsd
  - IDType: "02"=NIF-IVA, "04"=IDEnPaisResidencia, "06"=Otro documento Probatorio
  - Entidades españolas: elemento <NIF>
  - Entidades extranjeras: elemento <IDOtro>

Política de datos:
  El catálogo solo incluye identificadores fiscales publicados por la propia
  entidad en sus documentos oficiales, registro mercantil público, o
  comunicaciones regulatorias. Ningún dato ha sido inferido ni estimado.
  Los identificadores marcados con confianza "baja" o id_fiscal=None requieren
  verificación manual por parte del declarante contra su documentación
  contractual con el exchange.
"""

from dataclasses import dataclass, field
from typing import Optional


# ── CONSTANTES DE TIPO DE ID ──────────────────────────────────────────────────
#
# Uso interno. Los valores id_type_xsd mapean al atributo IDType del XSD AEAT.

TIPO_ID_NIF_ESP  = "NIF_ESP"      # NIF español → elemento <NIF> en XSD
TIPO_ID_VAT_EU   = "VAT_EU"       # Número IVA intracomunitario → IDType "02"
TIPO_ID_EIN_US   = "EIN_US"       # Employer ID Number (EEUU)  → IDType "04"
TIPO_ID_UEN_SG   = "UEN_SG"       # Unique Entity Number (Singapur) → IDType "04"
TIPO_ID_UID_CH   = "UID_CH"       # UID empresarial suizo → IDType "04"
TIPO_ID_OTRO     = "OTRO"         # Otro tipo de id conocido → IDType "06"
TIPO_ID_DESCONOCIDO = "DESCONOCIDO"  # Sin ID confirmado

# Mapa tipo_id → id_type_xsd (valor para IDOtro/IDType del XSD)
# Solo aplica para entidades extranjeras (las españolas usan <NIF>).
_ID_TYPE_XSD: dict = {
    TIPO_ID_VAT_EU:     "02",
    TIPO_ID_EIN_US:     "04",
    TIPO_ID_UEN_SG:     "04",
    TIPO_ID_UID_CH:     "04",
    TIPO_ID_OTRO:       "06",
    TIPO_ID_DESCONOCIDO: None,
    TIPO_ID_NIF_ESP:     None,   # No va en IDOtro; usa elemento NIF directamente
}

# ── CONSTANTES DE CONFIANZA ───────────────────────────────────────────────────

CONFIANZA_ALTA  = "alta"    # Dato verificado en fuente oficial primaria
CONFIANZA_MEDIA = "media"   # Dato publicado por la entidad pero no en reg. oficial
CONFIANZA_BAJA  = "baja"    # Dato no confirmado; requiere verificación del declarante


# ── DATACLASS ─────────────────────────────────────────────────────────────────

@dataclass
class CustodioFiscal:
    """
    Datos fiscales de un exchange/custodio para el Modelo 721.

    exchange_key:           Clave interna normalizada (ej. "binance").
    nombre_legal:           Razón social completa [XSD: NombreRazonSocial].
    codigo_pais_iso:        ISO 3166-1 alpha-2 [XSD: CodigoPais]. None = no determinado.
    extranjero:             True si está fuera de España → sujeto a 721.
    id_fiscal:              El número de identificación fiscal. None si no confirmado.
    tipo_id:                TIPO_ID_* constante que clasifica el id_fiscal.
    id_type_xsd:            Valor IDType del XSD AEAT para IDOtro ("02"/"04"/"06"/None).
    direccion:              Dirección registrada. None si no disponible.
    confianza:              CONFIANZA_* — grado de fiabilidad del id_fiscal.
    fuente:                 URL o descripción de la fuente del id_fiscal.
    requiere_verificacion:  True si el declarante debe confirmar el ID antes de presentar.
    nota:                   Información adicional para el declarante.
    advertencias:           Lista de advertencias específicas de este custodio.
    """
    exchange_key:          str
    nombre_legal:          str
    codigo_pais_iso:       Optional[str]
    extranjero:            bool

    id_fiscal:             Optional[str]
    tipo_id:               str
    id_type_xsd:           Optional[str]

    direccion:             Optional[str]

    confianza:             str
    fuente:                str
    requiere_verificacion: bool
    nota:                  Optional[str]
    advertencias:          list = field(default_factory=list)


# ── CATÁLOGO ──────────────────────────────────────────────────────────────────
#
# Clave: exchange_key normalizado (lowercase, sin espacios ni guiones).
# El declarante debe verificar el id_fiscal contra su documentación contractual.

CUSTODIOS_721: dict[str, CustodioFiscal] = {

    # ── España ────────────────────────────────────────────────────────────────

    "bit2me": CustodioFiscal(
        exchange_key          = "bit2me",
        nombre_legal          = "Bitnovo Solutions S.L.",
        codigo_pais_iso       = "ES",
        extranjero            = False,
        id_fiscal             = "B42521836",
        tipo_id               = TIPO_ID_NIF_ESP,
        id_type_xsd           = None,
        direccion             = (
            "C/ María de Molina 54, Planta 7ª, 28006 Madrid, España"
        ),
        confianza             = CONFIANZA_ALTA,
        fuente                = "Registro Mercantil de España (BORME)",
        requiere_verificacion = False,
        nota                  = (
            "Entidad española — NO sujeta a Modelo 721. "
            "NIF verificado en Registro Mercantil Central."
        ),
        advertencias          = [
            "Bit2Me opera bajo entidad española (ES). "
            "En principio no existe obligación de declarar en el Modelo 721. "
            "Si utilizas Bit2Me Pro u otro servicio con entidad EU distinta, "
            "verificar la entidad custodio en el contrato."
        ],
    ),

    # ── Países Bajos ──────────────────────────────────────────────────────────

    "bitvavo": CustodioFiscal(
        exchange_key          = "bitvavo",
        nombre_legal          = "Bitvavo B.V.",
        codigo_pais_iso       = "NL",
        extranjero            = True,
        id_fiscal             = "NL861859936B01",
        tipo_id               = TIPO_ID_VAT_EU,
        id_type_xsd           = "02",
        direccion             = (
            "Herengracht 420-422, 1017 BZ Amsterdam, Países Bajos"
        ),
        confianza             = CONFIANZA_MEDIA,
        fuente                = (
            "Número BTW publicado en la plataforma Bitvavo y facturas emitidas. "
            "KvK 66186566 — Kamer van Koophandel Países Bajos."
        ),
        requiere_verificacion = True,
        nota                  = (
            "Verificar el número BTW en la sección legal de bitvavo.com "
            "o en cualquier factura emitida por Bitvavo."
        ),
        advertencias          = [],
    ),

    # ── Estados Unidos ────────────────────────────────────────────────────────

    "kraken": CustodioFiscal(
        exchange_key          = "kraken",
        nombre_legal          = "Payward Europe Ltd.",
        codigo_pais_iso       = "IE",
        extranjero            = True,
        id_fiscal             = None,
        tipo_id               = TIPO_ID_DESCONOCIDO,
        id_type_xsd           = None,
        direccion             = None,
        confianza             = CONFIANZA_BAJA,
        fuente                = (
            "Usuarios UE operan habitualmente bajo Payward Europe Ltd. (IE). "
            "ID fiscal no confirmado en fuente pública verificada."
        ),
        requiere_verificacion = True,
        nota                  = (
            "Kraken opera con múltiples entidades legales según jurisdicción "
            "del cliente. Usuarios españoles: revisar el Acuerdo de Servicio "
            "en kraken.com para identificar la entidad custodio y su número "
            "de registro en CRO (Companies Registration Office, Irlanda)."
        ),
        advertencias          = [
            "Entidad legal custodio no confirmada automáticamente. "
            "Consultar la sección 'Términos de Servicio' en kraken.com "
            "e identificar la entidad Payward con la que se contrató el servicio."
        ],
    ),

    "coinbase": CustodioFiscal(
        exchange_key          = "coinbase",
        nombre_legal          = "Coinbase Europe Limited",
        codigo_pais_iso       = "IE",
        extranjero            = True,
        id_fiscal             = None,
        tipo_id               = TIPO_ID_DESCONOCIDO,
        id_type_xsd           = None,
        direccion             = None,
        confianza             = CONFIANZA_BAJA,
        fuente                = (
            "Usuarios UE operan habitualmente bajo Coinbase Europe Limited (IE). "
            "ID fiscal no confirmado en fuente pública verificada."
        ),
        requiere_verificacion = True,
        nota                  = (
            "Coinbase opera con múltiples entidades legales. Usuarios españoles: "
            "revisar las Condiciones de Uso en coinbase.com para identificar "
            "la entidad custodio y su número de registro CRO (Irlanda)."
        ),
        advertencias          = [
            "Entidad legal custodio no confirmada automáticamente. "
            "Consultar la sección 'Legal' en coinbase.com e identificar "
            "la entidad con la que se contrató el servicio."
        ],
    ),

    "uphold": CustodioFiscal(
        exchange_key          = "uphold",
        nombre_legal          = "Uphold HQ Inc.",
        codigo_pais_iso       = "US",
        extranjero            = True,
        id_fiscal             = None,
        tipo_id               = TIPO_ID_DESCONOCIDO,
        id_type_xsd           = None,
        direccion             = (
            "251 Little Falls Drive, Wilmington, Delaware 19808, EE.UU."
        ),
        confianza             = CONFIANZA_BAJA,
        fuente                = (
            "Dirección publicada en los Términos de Servicio de uphold.com. "
            "EIN (Employer Identification Number) no publicado en fuente accesible."
        ),
        requiere_verificacion = True,
        nota                  = (
            "Usuarios europeos pueden estar bajo Uphold Europe Ltd. (LT). "
            "Verificar la entidad custodio en los Términos de Servicio de uphold.com."
        ),
        advertencias          = [
            "Verificar si la custodia corresponde a Uphold HQ Inc. (US) "
            "o Uphold Europe Limited (LT) según los Términos de Servicio aceptados."
        ],
    ),

    # ── Singapur ──────────────────────────────────────────────────────────────

    "cryptocom": CustodioFiscal(
        exchange_key          = "cryptocom",
        nombre_legal          = "Foris DAX Asia Pte. Ltd.",
        codigo_pais_iso       = "SG",
        extranjero            = True,
        id_fiscal             = "201935164N",
        tipo_id               = TIPO_ID_UEN_SG,
        id_type_xsd           = "04",
        direccion             = (
            "1 Raffles Quay, North Tower, Level 26-01, Singapur 048583"
        ),
        confianza             = CONFIANZA_MEDIA,
        fuente                = (
            "UEN (Unique Entity Number) registrado en ACRA Singapore "
            "(Accounting and Corporate Regulatory Authority). "
            "Publicado en los documentos legales de crypto.com."
        ),
        requiere_verificacion = True,
        nota                  = (
            "Confirmar que la custodia corresponde a Foris DAX Asia (Exchange) "
            "y no a otra entidad del grupo (Foris DAX MT Ltd para Europa, etc.). "
            "Revisar los Términos de Uso según el tipo de cuenta."
        ),
        advertencias          = [
            "Crypto.com opera con diferentes entidades según tipo de servicio "
            "(Exchange, Earn, Card). Verificar entidad custodio en los Términos "
            "de Uso aplicables a tu cuenta."
        ],
    ),

    # ── Múltiples jurisdicciones (alta complejidad) ───────────────────────────

    "binance": CustodioFiscal(
        exchange_key          = "binance",
        nombre_legal          = "Binance Holdings Ltd.",
        codigo_pais_iso       = None,
        extranjero            = True,
        id_fiscal             = None,
        tipo_id               = TIPO_ID_DESCONOCIDO,
        id_type_xsd           = None,
        direccion             = None,
        confianza             = CONFIANZA_BAJA,
        fuente                = (
            "Binance opera con múltiples entidades legales: "
            "Binance Holdings Ltd. (KY), Binance Europe Services Ltd. (LT), "
            "Mercury Technologies UAB (LT), entre otras. "
            "La entidad custodio varía según el contrato."
        ),
        requiere_verificacion = True,
        nota                  = (
            "Identificar la entidad custodio real en el contrato aceptado "
            "en binance.com. Los usuarios europeos pueden estar bajo "
            "Binance Europe Services Ltd. (LT) o Mercury Technologies UAB (LT)."
        ),
        advertencias          = [
            "Binance opera con múltiples entidades legales. "
            "Es imprescindible identificar la entidad custodio exacta en los "
            "Términos de Uso de binance.com antes de cumplimentar el Modelo 721.",
            "El país del custodio (CodigoPais) no puede determinarse "
            "automáticamente para Binance. Requiere verificación manual."
        ],
    ),

    "nexo": CustodioFiscal(
        exchange_key          = "nexo",
        nombre_legal          = "Nexo AG",
        codigo_pais_iso       = None,
        extranjero            = True,
        id_fiscal             = None,
        tipo_id               = TIPO_ID_DESCONOCIDO,
        id_type_xsd           = None,
        direccion             = None,
        confianza             = CONFIANZA_BAJA,
        fuente                = (
            "Nexo opera con entidades en múltiples jurisdicciones: "
            "Nexo AG (CH), Nexo Financial LLC (BG), Nexo Capital Inc. (KY). "
            "La entidad custodio depende del contrato y tipo de cuenta."
        ),
        requiere_verificacion = True,
        nota                  = (
            "Revisar los Términos de Servicio en nexo.io para identificar "
            "la entidad custodio aplicable (CH, BG o KY). "
            "Para Nexo AG (Suiza): buscar el UID empresarial en zefix.ch."
        ),
        advertencias          = [
            "Nexo opera con varias entidades legales (CH, BG, KY). "
            "Identificar la entidad custodio en los Términos de Servicio "
            "de nexo.io antes de cumplimentar el Modelo 721."
        ],
    ),

    # ── Emiratos Árabes Unidos ─────────────────────────────────────────────────

    "bybit": CustodioFiscal(
        exchange_key          = "bybit",
        nombre_legal          = "Bybit Fintech Limited",
        codigo_pais_iso       = "AE",
        extranjero            = True,
        id_fiscal             = None,
        tipo_id               = TIPO_ID_DESCONOCIDO,
        id_type_xsd           = None,
        direccion             = None,
        confianza             = CONFIANZA_BAJA,
        fuente                = (
            "Bybit opera bajo Bybit Fintech Limited (AE) para usuarios generales. "
            "ID fiscal no confirmado en fuente pública verificada."
        ),
        requiere_verificacion = True,
        nota                  = (
            "Verificar la entidad custodio y datos de registro en los "
            "Términos de Servicio de bybit.com."
        ),
        advertencias          = [
            "Entidad legal y datos fiscales de Bybit requieren "
            "verificación manual contra los Términos de Servicio."
        ],
    ),
}


# ── FUNCIÓN DE CONSULTA ───────────────────────────────────────────────────────

def buscar_custodio(exchange_key: str) -> CustodioFiscal:
    """
    Devuelve el CustodioFiscal para el exchange indicado.

    Si el exchange_key no está en el catálogo, devuelve un CustodioFiscal
    genérico con confianza "baja" y requiere_verificacion=True.

    Args:
        exchange_key: Clave normalizada del exchange (lowercase, sin espacios).

    Returns:
        CustodioFiscal del catálogo, o entrada genérica si no existe.
    """
    key = _normalizar_key(exchange_key)
    custodio = CUSTODIOS_721.get(key)
    if custodio is not None:
        return custodio

    return CustodioFiscal(
        exchange_key          = key,
        nombre_legal          = key,
        codigo_pais_iso       = None,
        extranjero            = True,
        id_fiscal             = None,
        tipo_id               = TIPO_ID_DESCONOCIDO,
        id_type_xsd           = None,
        direccion             = None,
        confianza             = CONFIANZA_BAJA,
        fuente                = "Exchange no registrado en el catálogo de custodios.",
        requiere_verificacion = True,
        nota                  = (
            f"'{key}' no está en el catálogo de custodios. "
            "Identificar la entidad legal y su identificador fiscal manualmente "
            "antes de presentar el Modelo 721."
        ),
        advertencias          = [
            f"Exchange '{key}' no reconocido en el catálogo de custodios. "
            "Verificación manual completa requerida: nombre legal, país, "
            "identificador fiscal y dirección registrada."
        ],
    )


def _normalizar_key(exchange_key: str) -> str:
    """Normaliza la clave del exchange al mismo formato que CUSTODIOS_721."""
    return (
        exchange_key.lower()
        .replace(" ", "").replace("-", "").replace(".", "").replace("_", "")
    )


def to_dict_xsd(custodio: CustodioFiscal) -> dict:
    """
    Serializa un CustodioFiscal a un dict JSON-safe orientado al XSD AEAT.

    Devuelve la estructura directamente usable para IDPersonaEntidadSalvaguarda.
    Si id_fiscal es None, los campos XSD quedan en None (pendiente de completar).
    """
    usa_nif_esp = custodio.tipo_id == TIPO_ID_NIF_ESP

    return {
        # XSD: NombreRazonSocial
        "nombre_legal":    custodio.nombre_legal,
        # XSD: CodigoPais (custodio)
        "codigo_pais_iso": custodio.codigo_pais_iso,
        # Para entidades españolas: <NIF>
        "nif_esp":         custodio.id_fiscal if usa_nif_esp else None,
        # Para entidades extranjeras: <IDOtro>
        "id_otro": None if (usa_nif_esp or custodio.id_fiscal is None) else {
            "codigo_pais":  custodio.codigo_pais_iso,
            "id_type":      custodio.id_type_xsd,  # "02", "04", "07"
            "id":           custodio.id_fiscal,
        },
        # Metadatos internos (no van al XSD)
        "tipo_id":                custodio.tipo_id,
        "confianza":              custodio.confianza,
        "fuente":                 custodio.fuente,
        "requiere_verificacion":  custodio.requiere_verificacion,
        "nota":                   custodio.nota,
        "advertencias":           custodio.advertencias,
        # Dirección (XSD: Domicilio)
        "direccion":              custodio.direccion,
    }
