"""
Modelo 721 — Declaración informativa de monedas virtuales en el extranjero.
Genera la estructura de datos interna (JSON) para el Modelo 721.

FASE 2 — Lógica interna. Sin PDF, sin XML AEAT.
FASE 3A — Snapshot 31/12 correcto via posicion_a_fecha().

Referencia normativa:
  - Modelo 721 (procedimiento GI55), ejercicios desde 2022
  - XSD oficiales AEAT: Declaracion721.xsd, DeclaracionInformativa721.xsd
  - Ley 10/2021, DA decimocuarta LIRPF (modificada Ley 11/2021)

Uso:
    from modelo721 import generar_datos_modelo_721
    resultado = generar_datos_modelo_721(motor, exchange="binance", ejercicio=2024)
"""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, List, Optional, Tuple


# ── CATÁLOGO DE EXCHANGES ─────────────────────────────────────────────────────
#
# codigo_pais_iso: ISO 3166-1 alpha-2 según CountryType2 del XSD AEAT.
# extranjero: True = fuera de España → potencialmente sujeto a 721.
#             False = entidad española → NO sujeto a 721.
#             None = no determinado → requiere revisión manual.
# requiere_revision_pais: True cuando la entidad legal custodio es ambigua.

EXCHANGES_CATALOG: Dict[str, dict] = {
    "binance": {
        "nombre":                 "Binance",
        "pais_custodio":          "Islas Caimán / Malta / Lituania (varía según entidad)",
        "codigo_pais_iso":        None,
        "extranjero":             True,
        "requiere_revision_pais": True,
        "web":                    "https://www.binance.com",
        "nota":                   (
            "Binance opera con múltiples entidades legales (KY, MT, LT). "
            "Identificar la entidad custodia real según el contrato aceptado."
        ),
    },
    "bitvavo": {
        "nombre":                 "Bitvavo B.V.",
        "pais_custodio":          "Países Bajos",
        "codigo_pais_iso":        "NL",
        "extranjero":             True,
        "requiere_revision_pais": False,
        "web":                    "https://bitvavo.com",
        "nota":                   None,
    },
    "kraken": {
        "nombre":                 "Payward Inc. (Kraken)",
        "pais_custodio":          "Estados Unidos",
        "codigo_pais_iso":        "US",
        "extranjero":             True,
        "requiere_revision_pais": False,
        "web":                    "https://www.kraken.com",
        "nota":                   None,
    },
    "coinbase": {
        "nombre":                 "Coinbase Global, Inc.",
        "pais_custodio":          "Estados Unidos",
        "codigo_pais_iso":        "US",
        "extranjero":             True,
        "requiere_revision_pais": False,
        "web":                    "https://www.coinbase.com",
        "nota":                   None,
    },
    "bit2me": {
        "nombre":                 "Bitnovo Solutions S.L. (Bit2Me)",
        "pais_custodio":          "España",
        "codigo_pais_iso":        "ES",
        "extranjero":             False,
        "requiere_revision_pais": True,
        "web":                    "https://bit2me.com",
        "nota":                   (
            "Bit2Me tiene entidad española (ES). En principio NO sujeta a 721. "
            "Verificar si se utiliza Bit2Me Pro u otra entidad EU distinta."
        ),
    },
    "nexo": {
        "nombre":                 "Nexo AG / Nexo Financial LLC",
        "pais_custodio":          "Suiza / Bulgaria (múltiples entidades)",
        "codigo_pais_iso":        None,
        "extranjero":             True,
        "requiere_revision_pais": True,
        "web":                    "https://nexo.io",
        "nota":                   (
            "Nexo opera con entidades en CH y BG. "
            "Identificar la entidad custodio real antes de declarar."
        ),
    },
    "cryptocom": {
        "nombre":                 "Foris DAX Asia Pte. Ltd. (Crypto.com)",
        "pais_custodio":          "Singapur",
        "codigo_pais_iso":        "SG",
        "extranjero":             True,
        "requiere_revision_pais": True,
        "web":                    "https://crypto.com",
        "nota":                   (
            "Confirmar entidad custodio según tipo de cuenta (Exchange vs Earn)."
        ),
    },
    "uphold": {
        "nombre":                 "Uphold HQ Inc.",
        "pais_custodio":          "Estados Unidos",
        "codigo_pais_iso":        "US",
        "extranjero":             True,
        "requiere_revision_pais": False,
        "web":                    "https://uphold.com",
        "nota":                   None,
    },
    "bybit": {
        "nombre":                 "Bybit (BitGetaway Inc.)",
        "pais_custodio":          "Emiratos Árabes Unidos",
        "codigo_pais_iso":        "AE",
        "extranjero":             True,
        "requiere_revision_pais": True,
        "web":                    "https://www.bybit.com",
        "nota":                   "Entidad legal compleja. Confirmar jurisdicción.",
    },
}


# ── CATÁLOGO DE DENOMINACIONES ────────────────────────────────────────────────
#
# Clave: ticker (uppercase). Valor: nombre completo para DenominacionMonedaVirtual.

DENOMINACIONES_CRIPTO: Dict[str, str] = {
    # Principales
    "BTC":   "Bitcoin",
    "ETH":   "Ethereum",
    "BNB":   "BNB",
    "SOL":   "Solana",
    "XRP":   "XRP",
    "ADA":   "Cardano",
    "AVAX":  "Avalanche",
    "DOT":   "Polkadot",
    "MATIC": "Polygon",
    "LINK":  "Chainlink",
    "LTC":   "Litecoin",
    "DOGE":  "Dogecoin",
    "ATOM":  "Cosmos",
    "UNI":   "Uniswap",
    "NEAR":  "NEAR Protocol",
    "ICP":   "Internet Computer",
    "FIL":   "Filecoin",
    "TRX":   "TRON",
    "SHIB":  "Shiba Inu",
    "BCH":   "Bitcoin Cash",
    "XLM":   "Stellar Lumens",
    "ALGO":  "Algorand",
    "VET":   "VeChain",
    "EOS":   "EOS",
    "AAVE":  "Aave",
    "XMR":   "Monero",
    "SAND":  "The Sandbox",
    "MANA":  "Decentraland",
    "CRO":   "Cronos",
    "APT":   "Aptos",
    "OP":    "Optimism",
    "ARB":   "Arbitrum",
    "SUI":   "Sui",
    "INJ":   "Injective",
    "FTM":   "Fantom",
    "HBAR":  "Hedera",
    "GRT":   "The Graph",
    "STX":   "Stacks",
    "IMX":   "Immutable X",
    "FLOW":  "Flow",
    "EGLD":  "MultiversX",
    "KAVA":  "Kava",
    "ROSE":  "Oasis Network",
    # Stablecoins
    "USDT":  "Tether USD",
    "USDC":  "USD Coin",
    "BUSD":  "Binance USD",
    "FDUSD": "First Digital USD",
    "DAI":   "Dai",
    "TUSD":  "TrueUSD",
    "PYUSD": "PayPal USD",
}

# Stablecoins: su valor EUR requiere tipo de cambio EUR/USD externo.
_STABLECOINS: frozenset[str] = frozenset({
    "USDT", "USDC", "BUSD", "FDUSD", "DAI", "TUSD", "PYUSD",
})


# ── DATACLASS INTERNO ─────────────────────────────────────────────────────────

@dataclass
class Modelo721Entry:
    """
    Representa una fila del RegistroDetalle del Modelo 721.
    Un entry por (exchange, activo) a 31/12 del ejercicio.

    Campos marcados con [XSD] son los que se mapean directamente
    al XML AEAT cuando se genere en fases posteriores.
    """
    # Identificación del custodio [XSD: IDPersonaEntidadSalvaguarda]
    exchange:             str
    exchange_key:         str
    pais_custodio:        Optional[str]     # texto libre (no va al XSD directamente)
    codigo_pais_iso:      Optional[str]     # [XSD: CodigoPais] ISO 3166-1 alpha-2
    extranjero:           Optional[bool]    # indicador interno

    # Activo [XSD: TipoMonedaVirtual]
    activo:               str               # ticker
    denominacion:         str               # [XSD: DenominacionMonedaVirtual]
    siglas:               str               # [XSD: SiglasMonedaVirtual] ≤15 chars

    # Cantidades [XSD: NumMonedas, SaldoMonedasVirtuales]
    cantidad:             Decimal

    # Valoración [XSD: ValorMonedas, OrigenValorMonedas]
    valor_eur:            Optional[Decimal]  # None hasta que se provea precio externo
    origen_valor:         Optional[str]

    # Datos internos (no van al XSD)
    coste_base_fifo:      Decimal

    # Metadatos de la declaración [XSD: Clave, OrigenMonedaVirtual]
    clave:                str               # T=Titular (por defecto)
    origen_moneda_virtual: str             # A=Alta | M=Modificación | C=Baja
    fecha_referencia:     str               # 31-12-{ejercicio}

    # Control de calidad
    requiere_revision:    bool
    advertencias:         List[str] = field(default_factory=list)


# ── HELPERS PRIVADOS ──────────────────────────────────────────────────────────

def _normalizar_exchange_key(exchange: str) -> str:
    return (
        exchange.lower()
        .replace(" ", "").replace("-", "").replace(".", "").replace("_", "")
    )


def _get_exchange_info(exchange: str) -> dict:
    key = _normalizar_exchange_key(exchange)
    return EXCHANGES_CATALOG.get(key, {
        "nombre":                 exchange,
        "pais_custodio":          None,
        "codigo_pais_iso":        None,
        "extranjero":             None,
        "requiere_revision_pais": True,
        "web":                    None,
        "nota":                   (
            f"Exchange '{exchange}' no reconocido en el catálogo. "
            "Verificación manual completa requerida (país, entidad legal, NIF)."
        ),
    })


def _get_denominacion(ticker: str) -> Tuple[str, bool]:
    den = DENOMINACIONES_CRIPTO.get(ticker.upper())
    return (den, True) if den else (ticker, False)


# ── FUNCIÓN PRINCIPAL ─────────────────────────────────────────────────────────

def generar_datos_modelo_721(
    motor,
    exchange: str,
    ejercicio: int,
    clasificador=None,
) -> dict:
    """
    Genera la estructura de datos interna del Modelo 721 desde un MotorFIFO.

    Args:
        motor:        MotorFIFO procesado con TODAS las transacciones hasta
                      el 31/12 del ejercicio declarado (y años anteriores para
                      respetar el método FIFO). posicion_actual() refleja el
                      saldo a cierre del ejercicio.
        exchange:     Nombre del exchange (ej. "binance", "Bitvavo").
        ejercicio:    Año fiscal declarado (ej. 2024).
        clasificador: Reservado para integración futura (rendimientos, etc.).

    Returns:
        Dict JSON-serializable con estructura del Modelo 721.
        Todos los Decimal se serializan como strings.
    """
    fecha_ref   = f"31-12-{ejercicio}"
    fecha_corte = datetime(ejercicio, 12, 31, 23, 59, 59)
    posiciones  = motor.posicion_a_fecha(fecha_corte)

    exc_info = _get_exchange_info(exchange)
    exc_key  = _normalizar_exchange_key(exchange)

    entries:             List[Modelo721Entry] = []
    advertencias_globales: List[str]          = []

    # ── Advertencias a nivel de exchange ────────────────────────────────────
    if exc_info.get("codigo_pais_iso") is None:
        advertencias_globales.append(
            f"País del custodio para '{exc_info['nombre']}' no confirmado. "
            "Identificar la entidad legal responsable de la custodia antes de presentar."
        )
    if exc_info.get("extranjero") is None:
        advertencias_globales.append(
            "No se puede determinar automáticamente si el exchange es custodio "
            "extranjero. El Modelo 721 solo aplica a monedas virtuales custodiadas "
            "fuera de España. Verificar manualmente."
        )
    if exc_info.get("nota"):
        advertencias_globales.append(exc_info["nota"])

    # ── Construir entries por activo ─────────────────────────────────────────
    for posicion in posiciones:
        ticker   = posicion.activo.upper()
        cantidad = Decimal(str(posicion.cantidad_total)).quantize(
            Decimal("0.000001"), rounding=ROUND_HALF_UP
        )
        coste    = Decimal(str(posicion.coste_total)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

        if cantidad <= Decimal("0"):
            continue

        adv: List[str] = []

        # Denominación completa
        denominacion, conocida = _get_denominacion(ticker)
        if not conocida:
            adv.append(
                f"Denominación completa de '{ticker}' no reconocida en el catálogo. "
                "Verificar el nombre oficial de la moneda virtual."
            )

        # Valor de mercado a 31/12 — no calculable desde historial CSV
        if ticker in _STABLECOINS:
            adv.append(
                f"Stablecoin vinculada al USD. Valor EUR ≈ tipo de cambio EUR/USD "
                f"oficial (BCE) a 31/12/{ejercicio}. Actualizar manualmente."
            )
        else:
            adv.append(
                f"Valor de mercado de {ticker} a 31/12/{ejercicio} no calculable "
                "desde el historial de transacciones. Consultar precio oficial "
                "(CoinMarketCap, CoinGecko, cotización en el exchange) y actualizar."
            )

        entry = Modelo721Entry(
            exchange              = exc_info["nombre"],
            exchange_key          = exc_key,
            pais_custodio         = exc_info.get("pais_custodio"),
            codigo_pais_iso       = exc_info.get("codigo_pais_iso"),
            extranjero            = exc_info.get("extranjero"),
            activo                = ticker,
            denominacion          = denominacion,
            siglas                = ticker[:15],
            cantidad              = cantidad,
            valor_eur             = None,
            origen_valor          = None,
            coste_base_fifo       = coste,
            clave                 = "T",
            origen_moneda_virtual = "A",
            fecha_referencia      = fecha_ref,
            requiere_revision     = True,
            advertencias          = adv,
        )
        entries.append(entry)

    # ── Sin posiciones declarables ───────────────────────────────────────────
    if not entries:
        return {
            "modelo":                  "721",
            "ejercicio":               ejercicio,
            "fecha_referencia":        fecha_ref,
            "potencialmente_obligado": False,
            "informe_orientativo":     True,
            "total_valor_eur":         None,
            "exchanges":               [],
            "advertencias": [
                f"No se detectan posiciones con saldo positivo a 31/12/{ejercicio}. "
                "Si existían saldos y se liquidaron durante el año, podría igualmente "
                "existir obligación de declarar ejercicios anteriores. "
                "Consultar con asesor fiscal."
            ],
        }

    # ── ¿Potencialmente obligado? ────────────────────────────────────────────
    # Conservador: True si extranjero=True o si no se puede determinar (None).
    # Solo False si confirmamos que el exchange es español.
    potencialmente_obligado = exc_info.get("extranjero") is not False

    # ── Serializar a dict JSON-safe ──────────────────────────────────────────
    activos_json = [
        {
            "activo":                e.activo,
            "denominacion":          e.denominacion,
            "siglas":                e.siglas,
            "cantidad":              str(e.cantidad),
            "valor_eur":             str(e.valor_eur) if e.valor_eur is not None else None,
            "origen_valor":          e.origen_valor,
            "coste_base_fifo":       str(e.coste_base_fifo),
            "clave":                 e.clave,
            "origen_moneda_virtual": e.origen_moneda_virtual,
            "fecha_referencia":      e.fecha_referencia,
            "requiere_revision":     e.requiere_revision,
            "advertencias":          e.advertencias,
        }
        for e in entries
    ]

    advertencias_finales = advertencias_globales + [
        "El valor de mercado de cada activo a 31/12 debe obtenerse de una fuente "
        "oficial y no puede calcularse automáticamente desde el historial. "
        "Este informe es orientativo y NO constituye asesoramiento fiscal ni legal.",
    ]

    return {
        "modelo":                  "721",
        "ejercicio":               ejercicio,
        "fecha_referencia":        fecha_ref,
        "potencialmente_obligado": potencialmente_obligado,
        "informe_orientativo":     True,
        "total_valor_eur":         None,
        "exchanges": [
            {
                "exchange":          exc_info["nombre"],
                "exchange_key":      exc_key,
                "pais_custodio":     exc_info.get("pais_custodio"),
                "codigo_pais_iso":   exc_info.get("codigo_pais_iso"),
                "extranjero":        exc_info.get("extranjero"),
                "nif_custodio":      None,
                "web_custodio":      exc_info.get("web"),
                "requiere_revision": (
                    exc_info.get("requiere_revision_pais", True)
                    or any(e.requiere_revision for e in entries)
                ),
                "activos":           activos_json,
            }
        ],
        "advertencias": advertencias_finales,
    }
