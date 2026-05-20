"""
Generador XML Modelo 721 — AEAT.

FASE 3B.3 — Generación del fichero XML presentable a la AEAT.

Conforme a los esquemas XSD oficiales publicados por la AEAT:
  · DeclaracionInformativa721.xsd  (namespace ddii)
  · Declaracion721.xsd             (namespace ddiiD — elemento raíz Declaracion)

Descarga: https://sede.agenciatributaria.gob.es → Procedimiento GI55 → Esquemas721.zip

IMPORTANTE:
  Antes de presentar a la AEAT, el declarante o su asesor debe:
    1. Validar el fichero contra los XSD oficiales con validar_xml_contra_xsd().
    2. Verificar los datos del custodio (IDPersonaEntidadSalvaguarda).
    3. Firmar el fichero si el canal de presentación lo requiere.

Estados del XML:
  BLOQUEADO — xml_generable=False. No se puede generar:
    · Activos sin precio a 31/12 (ValorMonedas vacío → XSD inválido).
    · NIF del declarante no proporcionado o con formato inválido.

  BORRADOR  — xml_generable=True, es_borrador=True. Se genera pero:
    · Custodio extranjero sin id_fiscal → IDOtro placeholder (PENDIENTE/06).
    · Custodio con confianza_id='baja' → datos sin verificar.
    · Valor total < 50.000 EUR → posible ausencia de obligación de presentar.

  VÁLIDO    — xml_generable=True, es_borrador=False.
    Todos los datos están presentes y verificados (confianza media o alta).
"""

import os
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from typing import List, Optional, Tuple
from xml.dom.minidom import parseString


# ── NAMESPACES ─────────────────────────────────────────────────────────────────

#: Namespace del esquema genérico de declaraciones informativas (DeclaracionInformativa.xsd)
NS_DDII = (
    "https://www2.agenciatributaria.gob.es/static_files/common/internet/"
    "dep/aplicaciones/es/aeat/ddii/enol/ws/DeclaracionInformativa.xsd"
)

#: Namespace del esquema específico del Modelo 721 (Declaracion.xsd — elemento raíz)
NS_DDIID = (
    "https://www2.agenciatributaria.gob.es/static_files/common/internet/"
    "dep/aplicaciones/es/aeat/ddii/enol/ws/Declaracion.xsd"
)

ET.register_namespace("ddiiD", NS_DDIID)
ET.register_namespace("ddii",  NS_DDII)


def _d(name: str) -> str:
    """Nombre de tag en namespace ddiiD (Declaracion.xsd — raíz)."""
    return f"{{{NS_DDIID}}}{name}"


def _i(name: str) -> str:
    """Nombre de tag en namespace ddii (DeclaracionInformativa.xsd — contenido)."""
    return f"{{{NS_DDII}}}{name}"


# ── CONSTANTES ─────────────────────────────────────────────────────────────────

#: Umbral de obligación de presentar (art. 1 RD 249/2023).
UMBRAL_DECLARACION_EUR = Decimal("50000.00")

#: TipoComunicacion — valores válidos según ClaveTipoComunicacionType del XSD.
TIPO_ALTA         = "A0"   # Alta: nuevo registro
TIPO_MODIFICACION = "A1"   # Modificación: reemplaza declaración previa

_TIPOS_VALIDOS = frozenset({TIPO_ALTA, TIPO_MODIFICACION})

#: Alias de compatibilidad con el código anterior a la validación XSD.
#: TIPO_INCIDENCIAS == TIPO_ALTA, TIPO_COMPLEMENTARIA == TIPO_MODIFICACION.
#: TIPO_SUSTITUTIVA no existe en el XSD oficial.
TIPO_INCIDENCIAS    = TIPO_ALTA
TIPO_COMPLEMENTARIA = TIPO_MODIFICACION

# Regex formato NIF/NIE/CIF español (9 caracteres)
_NIF_RE = re.compile(r"^[A-Z0-9][0-9]{7}[A-Z0-9]$", re.IGNORECASE)

#: Placeholder para BORRADOR cuando el custodio no tiene ID confirmado.
#: IDType "06" = "Otro documento Probatorio" (PersonaFisicaJuridicaIDTypeType).
_PLACEHOLDER_ID     = "PENDIENTE"
_PLACEHOLDER_IDTYPE = "06"

_DIR_XSD = os.path.dirname(os.path.abspath(__file__))


# ── DATACLASS DE VALIDACIÓN ────────────────────────────────────────────────────

@dataclass
class ValidacionXML:
    """
    Resultado de validar si un conjunto de datos 721 es generable como XML.

    xml_generable:     True si se puede generar el XML (aunque sea borrador).
    es_borrador:       True si el XML contiene datos pendientes de verificar.
    bloqueantes:       Razones por las que xml_generable=False.
    advertencias:      Avisos que hacen es_borrador=True.
    por_debajo_umbral: True si el valor total < 50.000 EUR.
    """
    xml_generable:     bool
    es_borrador:       bool
    bloqueantes:       List[str] = field(default_factory=list)
    advertencias:      List[str] = field(default_factory=list)
    por_debajo_umbral: bool      = False


# ── EXCEPCIÓN ──────────────────────────────────────────────────────────────────

class ErrXMLBloqueado(Exception):
    """El XML no puede generarse porque hay datos críticos pendientes."""
    def __init__(self, bloqueantes: List[str]) -> None:
        self.bloqueantes = bloqueantes
        super().__init__(f"XML bloqueado: {'; '.join(bloqueantes)}")


# ── VALIDACIÓN ─────────────────────────────────────────────────────────────────

def validar_para_xml(
    datos: dict,
    nif_declarante: Optional[str],
) -> ValidacionXML:
    """
    Analiza los datos 721 y devuelve el estado de validación del XML.

    Args:
        datos:           Dict resultado de generar_datos_modelo_721() (ya enriquecido).
        nif_declarante:  NIF/NIE del declarante. None o "" bloquea la generación.

    Returns:
        ValidacionXML con el estado y los mensajes correspondientes.
    """
    bloqueantes:  List[str] = []
    advertencias: List[str] = []

    # ── BLOQUEANTES ────────────────────────────────────────────────────────────

    # 1. NIF del declarante
    nif_clean = (nif_declarante or "").strip()
    if not nif_clean:
        bloqueantes.append(
            "NIF del declarante no proporcionado. "
            "El campo 'nif_declarante' es obligatorio para generar el XML."
        )
    elif not _nif_valido(nif_clean):
        bloqueantes.append(
            f"NIF del declarante '{nif_clean}' no tiene formato válido. "
            "Formato esperado: NIF (8 dígitos + letra), NIE (X/Y/Z + 7 dígitos + letra) "
            "o CIF (letra + 7 dígitos + dígito/letra)."
        )

    # 2. Activos sin precio EUR a 31/12
    sin_precio: List[str] = []
    for exc in datos.get("exchanges", []):
        if exc.get("extranjero") is False:
            continue   # Entidades españolas no van al XML
        for activo in exc.get("activos", []):
            if activo.get("valor_eur") is None:
                sin_precio.append(activo["activo"])
    if sin_precio:
        tickers_str = ", ".join(sorted(set(sin_precio)))
        bloqueantes.append(
            f"ValorMonedas no disponible para: {tickers_str}. "
            "Obtener precio a 31/12 antes de generar el XML."
        )

    xml_generable = len(bloqueantes) == 0

    # ── ADVERTENCIAS (solo si no hay bloqueantes) ──────────────────────────────

    if xml_generable:
        sin_id:         List[str] = []
        confianza_baja: List[str] = []
        sin_pais:       List[str] = []

        for exc in datos.get("exchanges", []):
            if exc.get("extranjero") is False:
                continue
            key = exc.get("exchange_key") or exc.get("exchange", "")
            if exc.get("nif_custodio") is None:
                sin_id.append(key)
            if exc.get("confianza_id") == "baja":
                confianza_baja.append(key)
            if exc.get("codigo_pais_iso") is None:
                sin_pais.append(key)

        if sin_id:
            advertencias.append(
                f"IDPersonaEntidadSalvaguarda sin identificador fiscal para: "
                f"{', '.join(sin_id)}. "
                "El XML se generará con IDOtro placeholder (IDType=06, ID=PENDIENTE). "
                "Completar manualmente antes de presentar a la AEAT."
            )
        if confianza_baja:
            advertencias.append(
                f"Datos del custodio con confianza baja (sin verificar contra fuente oficial): "
                f"{', '.join(confianza_baja)}. "
                "Verificar la entidad legal y su identificador antes de presentar."
            )
        if sin_pais:
            advertencias.append(
                f"CodigoPais del custodio no confirmado para: {', '.join(sin_pais)}. "
                "Verificar el país del custodio antes de presentar."
            )

    # ── UMBRAL 50.000 EUR ──────────────────────────────────────────────────────

    por_debajo_umbral = False
    total_str = datos.get("total_valor_eur")
    if total_str is not None:
        total = Decimal(str(total_str))
        if total < UMBRAL_DECLARACION_EUR:
            por_debajo_umbral = True
            advertencias.append(
                f"Valor total declarable: {_fmt_eur(total)} EUR < 50.000 EUR. "
                "Con carácter general no existe obligación de presentar el Modelo 721 "
                "si el valor de los activos en el extranjero no supera este umbral. "
                "Consultar con asesor fiscal para confirmar."
            )

    es_borrador = xml_generable and len(advertencias) > 0

    return ValidacionXML(
        xml_generable     = xml_generable,
        es_borrador       = es_borrador,
        bloqueantes       = bloqueantes,
        advertencias      = advertencias,
        por_debajo_umbral = por_debajo_umbral,
    )


# ── GENERADOR PRINCIPAL ────────────────────────────────────────────────────────

def generar_xml_721(
    datos: dict,
    nif_declarante: str,
    nombre_declarante: str,
    tipo_comunicacion: str = TIPO_ALTA,
    forzar_borrador:   bool = False,
) -> Tuple[str, ValidacionXML]:
    """
    Genera el XML del Modelo 721 conforme a Declaracion721.xsd.

    Estructura generada (según XSD AEAT):
      <ddiiD:Declaracion>
        <ddii:Cabecera>
          <ddii:TipoComunicacion>A0|A1</ddii:TipoComunicacion>
          <ddii:Modelo>721</ddii:Modelo>
          <ddii:Ejercicio>YYYY</ddii:Ejercicio>
          <ddii:IDVersionModelo>1.0</ddii:IDVersionModelo>
          <ddii:IDDeclarante>
            <ddii:NIF>...</ddii:NIF>
            <ddii:NombreRazon>...</ddii:NombreRazon>
          </ddii:IDDeclarante>
        </ddii:Cabecera>
        <ddii:RegistroDeDetalle>           <!-- uno por activo extranjero -->
          <ddii:IDRegistroDetalle>1</ddii:IDRegistroDetalle>
          <ddii:RegistroDetalle>
            <ddii:Clave>T</ddii:Clave>
            <ddii:IDPersonaEntidadSalvaguarda>
              <ddii:NombreRazon>...</ddii:NombreRazon>
              <ddii:IDOtro>...</ddii:IDOtro>   <!-- o <ddii:NIF> -->
              <ddii:DomicilioEntidadSalvaguarda>...</ddii:DomicilioEntidadSalvaguarda>
            </ddii:IDPersonaEntidadSalvaguarda>
            <ddii:TipoMonedaVirtual>
              <ddii:DenominacionMonedaVirtual>...</ddii:DenominacionMonedaVirtual>
              <ddii:SiglasMonedaVirtual>...</ddii:SiglasMonedaVirtual>
            </ddii:TipoMonedaVirtual>
            <ddii:NumMonedas>...</ddii:NumMonedas>
            <ddii:ValorMonedas>...</ddii:ValorMonedas>
            <ddii:OrigenValorMonedas>...</ddii:OrigenValorMonedas>
            <ddii:SaldoMonedasVirtuales>...</ddii:SaldoMonedasVirtuales>
            <ddii:OrigenMonedaVirtual>A|M|C</ddii:OrigenMonedaVirtual>
          </ddii:RegistroDetalle>
        </ddii:RegistroDeDetalle>
      </ddiiD:Declaracion>

    Args:
        datos:              Dict enriquecido de generar_datos_modelo_721().
        nif_declarante:     NIF/NIE/CIF del declarante (obligatorio, 9 chars).
        nombre_declarante:  Nombre o razón social del declarante (obligatorio, máx. 120).
        tipo_comunicacion:  "A0" (Alta, por defecto) o "A1" (Modificación).
        forzar_borrador:    Si True, marca el XML como borrador aunque sea válido.

    Returns:
        Tuple (xml_string, ValidacionXML).

    Raises:
        ErrXMLBloqueado si xml_generable=False.
        ValueError si tipo_comunicacion inválido o nombre_declarante vacío.
    """
    # Compatibilidad con valores previos al descubrimiento del XSD oficial.
    _compat = {"I": TIPO_ALTA, "C": TIPO_MODIFICACION, "S": TIPO_ALTA}
    if tipo_comunicacion in _compat:
        tipo_comunicacion = _compat[tipo_comunicacion]

    if tipo_comunicacion not in _TIPOS_VALIDOS:
        raise ValueError(
            f"tipo_comunicacion '{tipo_comunicacion}' inválido. "
            f"Valores válidos: {', '.join(sorted(_TIPOS_VALIDOS))}."
        )
    if not nombre_declarante or not nombre_declarante.strip():
        raise ValueError("nombre_declarante no puede estar vacío.")

    validacion = validar_para_xml(datos, nif_declarante)
    if not validacion.xml_generable:
        raise ErrXMLBloqueado(validacion.bloqueantes)

    es_borrador  = validacion.es_borrador or forzar_borrador
    ejercicio    = datos["ejercicio"]
    nif_clean    = nif_declarante.strip().upper()
    nombre_clean = nombre_declarante.strip()[:120]

    # ── Raíz: Declaracion (namespace ddiiD) ──────────────────────────────────
    root = ET.Element(_d("Declaracion"))

    # ── Cabecera ──────────────────────────────────────────────────────────────
    cab = ET.SubElement(root, _i("Cabecera"))
    _elem(cab, _i("TipoComunicacion"), tipo_comunicacion)
    _elem(cab, _i("Modelo"),           "721")
    _elem(cab, _i("Ejercicio"),        str(ejercicio))
    _elem(cab, _i("IDVersionModelo"),  "1.0")
    id_dec = ET.SubElement(cab, _i("IDDeclarante"))
    _elem(id_dec, _i("NIF"),         nif_clean)
    _elem(id_dec, _i("NombreRazon"), nombre_clean)

    # ── RegistroDeDetalle — uno por (custodio_extranjero, moneda) ─────────────
    seq = 0
    for exc in datos.get("exchanges", []):
        if exc.get("extranjero") is False:
            continue  # Entidades españolas no van al XML del 721

        for activo in exc.get("activos", []):
            if activo.get("valor_eur") is None:
                continue  # Bloqueado por validación; por seguridad se salta

            seq += 1

            # Wrapper RegistroDeDetalle con IDRegistroDetalle
            reg_wrapper = ET.SubElement(root, _i("RegistroDeDetalle"))
            _elem(reg_wrapper, _i("IDRegistroDetalle"), str(seq))

            reg = ET.SubElement(reg_wrapper, _i("RegistroDetalle"))

            # Clave — al nivel de RegistroDetalle (NO dentro de TipoMonedaVirtual)
            _elem(reg, _i("Clave"), activo.get("clave", "T"))

            # IDPersonaEntidadSalvaguarda
            _build_id_persona_entidad(reg, exc)

            # TipoMonedaVirtual — solo denominación y siglas (XSD: 2 elementos)
            tm = ET.SubElement(reg, _i("TipoMonedaVirtual"))
            _elem(tm, _i("DenominacionMonedaVirtual"), activo["denominacion"][:50])
            _elem(tm, _i("SiglasMonedaVirtual"),       activo["siglas"][:15])

            # Campos numéricos y de origen — hermanos de TipoMonedaVirtual
            _elem(reg, _i("NumMonedas"),
                  _fmt_cantidad(activo["cantidad"]))
            _elem(reg, _i("ValorMonedas"),
                  _fmt_valor(Decimal(activo["valor_eur"])))
            _elem(reg, _i("OrigenValorMonedas"),
                  (activo.get("origen_valor") or "O")[:50])

            # FechaFinCondicion — opcional, formato DD-MM-YYYY
            if activo.get("fecha_fin_condicion"):
                _elem(reg, _i("FechaFinCondicion"), activo["fecha_fin_condicion"])

            _elem(reg, _i("SaldoMonedasVirtuales"),
                  _fmt_cantidad(activo["cantidad"]))
            _elem(reg, _i("OrigenMonedaVirtual"),
                  activo.get("origen_moneda_virtual", "A"))

    # ── Serializar con formato ────────────────────────────────────────────────
    xml_str = _pretty_xml(root, es_borrador)
    return xml_str, validacion


# ── VALIDACIÓN XSD ─────────────────────────────────────────────────────────────

def validar_xml_contra_xsd(xml_str: str) -> Tuple[bool, List[str]]:
    """
    Valida el XML generado contra los XSD oficiales de la AEAT.

    Requiere el paquete 'xmlschema' (pip install xmlschema).
    Los ficheros Declaracion721.xsd y DeclaracionInformativa721.xsd deben
    estar en el mismo directorio que este módulo.

    Args:
        xml_str:  XML en formato string (resultado de generar_xml_721).

    Returns:
        Tuple (valido: bool, errores: List[str]).
        Si valido=True, errores es una lista vacía.
    """
    try:
        import xmlschema  # type: ignore
    except ImportError:
        raise ImportError(
            "xmlschema no está instalado. Ejecuta: pip install xmlschema"
        )

    xsd_path = os.path.join(_DIR_XSD, "Declaracion721.xsd")
    if not os.path.exists(xsd_path):
        raise FileNotFoundError(
            f"XSD no encontrado: {xsd_path}. "
            "Descarga Esquemas721.zip de la AEAT y extrae los .xsd en este directorio."
        )

    schema  = xmlschema.XMLSchema(xsd_path)
    errores = [str(e) for e in schema.iter_errors(xml_str)]
    return len(errores) == 0, errores


# ── HELPERS PRIVADOS ──────────────────────────────────────────────────────────

def _nif_valido(nif: str) -> bool:
    """Validación básica de formato NIF/NIE/CIF español (9 caracteres)."""
    return bool(_NIF_RE.match(nif.upper()))


def _elem(parent: ET.Element, tag: str, text: Optional[str] = None) -> ET.Element:
    """Crea un subelemento. Si text es None no establece contenido de texto."""
    el = ET.SubElement(parent, tag)
    if text is not None:
        el.text = text
    return el


def _fmt_eur(valor: Decimal) -> str:
    """Formatea un importe EUR con 2 decimales."""
    return str(valor.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _fmt_valor(valor: Decimal) -> str:
    """
    Formatea ValorMonedas conforme a Decimal10.14Type del XSD.
    Usa 2 decimales (formato monetario estándar en EUR).
    """
    return str(valor.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _fmt_cantidad(cantidad_str: str) -> str:
    """Formatea NumMonedas/SaldoMonedasVirtuales con 6 decimales (Decimal20.6Type)."""
    return str(Decimal(cantidad_str).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP))


def _build_id_persona_entidad(parent: ET.Element, exc: dict) -> None:
    """
    Construye IDPersonaEntidadSalvaguarda conforme al XSD.

    Secuencia según XSD (complexType inline en RegistroDeDetalleType):
      1. NombreRazon         (required, TextMax120Type)
      2. CHOICE (required):
           NIF               → entidad española (NIFType, 9 chars)
           IDOtro            → entidad extranjera o placeholder
             CodigoPais      (optional, CountryType2)
             IDType          (required, "02"–"06")
             ID              (required, TextMax20Type)
      3. DomicilioEntidadSalvaguarda (optional):
           CodigoPais        (required dentro del domicilio)
           NombreMunicipio   (optional, max 30)
           NombreVia         (optional, max 50)
           Numeracion        (optional, max 5 digits)
           CodigoPostal      (optional, max 12)
           Complemento       (optional, max 50)
      4. DireccionSitioWebEntidadSalvaguarda (optional, max 50)

    Para BORRADOR (custodio sin ID): se inserta IDOtro con IDType=06 (Otro
    documento Probatorio) e ID=PENDIENTE para cumplir la restricción choice.
    """
    id_el = ET.SubElement(parent, _i("IDPersonaEntidadSalvaguarda"))

    # 1. NombreRazon — siempre primero
    nombre = (exc.get("nombre_legal") or exc.get("exchange", ""))[:120]
    _elem(id_el, _i("NombreRazon"), nombre)

    # 2. CHOICE: NIF (española) | IDOtro (extranjera o placeholder)
    nif_esp = exc.get("nif_esp")
    id_otro = exc.get("id_otro")

    if nif_esp:
        # Entidad española → elemento <NIF>
        _elem(id_el, _i("NIF"), nif_esp)

    elif id_otro and id_otro.get("id"):
        # Entidad extranjera con ID confirmado → <IDOtro>
        id_otro_el = ET.SubElement(id_el, _i("IDOtro"))
        if id_otro.get("codigo_pais"):
            _elem(id_otro_el, _i("CodigoPais"), id_otro["codigo_pais"])
        _elem(id_otro_el, _i("IDType"), str(id_otro["id_type"]))
        _elem(id_otro_el, _i("ID"),     str(id_otro["id"])[:20])

    else:
        # Sin ID confirmado → placeholder para cumplir el <choice> del XSD
        # (el XML queda como BORRADOR — NO presentar sin corregir este campo)
        id_otro_el = ET.SubElement(id_el, _i("IDOtro"))
        _elem(id_otro_el, _i("IDType"), _PLACEHOLDER_IDTYPE)
        _elem(id_otro_el, _i("ID"),     _PLACEHOLDER_ID)

    # 3. DomicilioEntidadSalvaguarda — solo si tenemos CodigoPais confirmado
    pais = exc.get("codigo_pais_iso")
    if pais:
        dom_el = ET.SubElement(id_el, _i("DomicilioEntidadSalvaguarda"))
        _elem(dom_el, _i("CodigoPais"), pais)
        # NombreVia — máx. 50 chars; truncar en espacio limpio si es más larga
        if exc.get("direccion"):
            dir_raw = exc["direccion"]
            if len(dir_raw) > 50:
                # Cortar en el último espacio dentro del límite (evita corte de palabra)
                dir_raw = dir_raw[:50].rsplit(" ", 1)[0] or dir_raw[:50]
            _elem(dom_el, _i("NombreVia"), dir_raw)


def _pretty_xml(root: ET.Element, es_borrador: bool) -> str:
    """
    Serializa el árbol ElementTree a XML indentado con namespaces ddii/ddiiD.

    Si es_borrador=True inserta un comentario XML tras la declaración
    <?xml ...?> para advertir al lector humano.
    """
    raw    = ET.tostring(root, encoding="unicode", xml_declaration=False)
    dom    = parseString(f'<?xml version="1.0" encoding="UTF-8"?>{raw}')
    pretty = dom.toprettyxml(indent="  ", encoding=None)

    # toprettyxml(encoding=None) genera <?xml version="1.0" ?> sin charset.
    # Reemplazamos la primera línea por la declaración correcta con UTF-8.
    lines = pretty.split("\n")
    if lines and lines[0].startswith("<?xml"):
        lines[0] = '<?xml version="1.0" encoding="UTF-8"?>'

    # Comentario de borrador en segunda posición si procede.
    if es_borrador:
        comment = (
            "<!-- [BORRADOR] XML generado con datos pendientes de verificación. "
            "NO presentar a la AEAT sin revisar previamente todos los avisos. -->"
        )
        lines.insert(1, comment)

    return "\n".join(lines)
