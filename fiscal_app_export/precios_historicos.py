"""
Precios históricos a 31/12 para el Modelo 721.

FASE 3B.1 — Servicio interno de valoración.

Recibe un ticker (ej. "BTC") y un ejercicio (ej. 2024) y devuelve el precio
en EUR a cierre del año (31/12 del ejercicio) con trazabilidad completa.

Fuentes utilizadas (por prioridad):
  1. CoinGecko (History API v3) — cryptos con ID registrado.
  2. BCE (ECB Data API) — tipo de cambio EUR/USD para stablecoins USD.
  3. no_disponible — cuando ninguna fuente resuelve el precio.

Uso:
    from precios_historicos import obtener_precios_historicos, enriquecer_721_con_precios
    precios = obtener_precios_historicos(["BTC", "ETH", "USDT"], ejercicio=2024)
    datos_enriquecidos = enriquecer_721_con_precios(datos_721, precios)
"""

import os
import time
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, List, Optional

import requests

logger = logging.getLogger(__name__)


# ── CONFIGURACIÓN ──────────────────────────────────────────────────────────────

_CG_API_KEY  = os.environ.get("COINGECKO_API_KEY", "")
_CG_BASE     = (
    "https://pro-api.coingecko.com/api/v3"
    if _CG_API_KEY else
    "https://api.coingecko.com/api/v3"
)
_CG_THROTTLE = 1.2   # segundos entre requests (free tier ≈ 30 req/min)
_CG_TIMEOUT  = 8     # segundos de timeout HTTP


# ── CONSTANTES DE FUENTE ───────────────────────────────────────────────────────

FUENTE_COINGECKO    = "coingecko"
FUENTE_ESTIMADO_BCE = "estimado_bce_eurusd"
FUENTE_NO_DISPONIBLE = "no_disponible"
FUENTE_FECHA_FUTURA  = "fecha_futura"


# ── CATÁLOGO COINGECKO ─────────────────────────────────────────────────────────
#
# Clave: ticker uppercase. Valor: CoinGecko ID exacto.
# Verificar en: https://api.coingecko.com/api/v3/coins/list

COINGECKO_IDS: Dict[str, str] = {
    # Bitcoin / Ethereum
    "BTC":   "bitcoin",
    "ETH":   "ethereum",
    "WBTC":  "wrapped-bitcoin",
    "WETH":  "weth",
    # BNB ecosystem
    "BNB":   "binancecoin",
    "CAKE":  "pancakeswap-token",
    # Solana ecosystem
    "SOL":   "solana",
    "RAY":   "raydium",
    "BONK":  "bonk",
    # L1 / L2 principales
    "XRP":   "ripple",
    "ADA":   "cardano",
    "AVAX":  "avalanche-2",
    "DOT":   "polkadot",
    "MATIC": "matic-network",
    "POL":   "matic-network",   # rebranding Polygon
    "LINK":  "chainlink",
    "LTC":   "litecoin",
    "DOGE":  "dogecoin",
    "SHIB":  "shiba-inu",
    "PEPE":  "pepe",
    "FLOKI": "floki",
    "ATOM":  "cosmos",
    "UNI":   "uniswap",
    "NEAR":  "near",
    "ICP":   "internet-computer",
    "FIL":   "filecoin",
    "TRX":   "tron",
    "BCH":   "bitcoin-cash",
    "XLM":   "stellar",
    "ALGO":  "algorand",
    "VET":   "vechain",
    "EOS":   "eos",
    "AAVE":  "aave",
    "XMR":   "monero",
    "SAND":  "the-sandbox",
    "MANA":  "decentraland",
    "CRO":   "crypto-com-chain",
    "APT":   "aptos",
    "OP":    "optimism",
    "ARB":   "arbitrum",
    "SUI":   "sui",
    "INJ":   "injective-protocol",
    "FTM":   "fantom",
    "HBAR":  "hedera-hashgraph",
    "GRT":   "the-graph",
    "STX":   "blockstack",
    "IMX":   "immutable-x",
    "FLOW":  "flow",
    "EGLD":  "elrond-erd-2",
    "KAVA":  "kava",
    "ROSE":  "oasis-network",
    "FET":   "fetch-ai",
    "RUNE":  "thorchain",
    "LDO":   "lido-dao",
    "MKR":   "maker",
    "SNX":   "havven",
    "CRV":   "curve-dao-token",
    "COMP":  "compound-governance-token",
    "BAL":   "balancer",
    "SUSHI": "sushi",
    "YFI":   "yearn-finance",
    "1INCH": "1inch",
    "ENS":   "ethereum-name-service",
    "LRC":   "loopring",
    "ZRX":   "0x",
    "BAT":   "basic-attention-token",
    "ANKR":  "ankr",
    "CHZ":   "chiliz",
    "GALA":  "gala",
    "AXS":   "axie-infinity",
    "NEXO":  "nexo",
    "COTI":  "coti",
    "XTZ":   "tezos",
    "ZEC":   "zcash",
    "DASH":  "dash",
    "NEO":   "neo",
    "IOTA":  "iota",
    "WAVES": "waves",
    "ZIL":   "zilliqa",
    "QTUM":  "qtum",
    "ONT":   "ontology",
    # Stablecoins — registradas aquí aunque se resuelven por BCE para valor EUR
    "USDT":  "tether",
    "USDC":  "usd-coin",
    "BUSD":  "binance-usd",
    "FDUSD": "first-digital-usd",
    "DAI":   "dai",
    "TUSD":  "true-usd",
    "PYUSD": "paypal-usd",
    "USDP":  "paxos-standard",
    "GUSD":  "gemini-dollar",
    "FRAX":  "frax",
    "LUSD":  "liquity-usd",
}

# Stablecoins USD: su precio en EUR se obtiene vía BCE (tipo de cambio EUR/USD).
_STABLECOINS_USD: frozenset = frozenset({
    "USDT", "USDC", "BUSD", "FDUSD", "DAI", "TUSD", "PYUSD",
    "USDP", "GUSD", "FRAX", "LUSD",
})

# Fragmentos de advertencia que enriquecer_721_con_precios debe filtrar/reemplazar
_ADV_PRECIO_PENDIENTE: tuple = (
    "Valor de mercado de",
    "Stablecoin vinculada al USD",
)


# ── CACHÉ EN MEMORIA ───────────────────────────────────────────────────────────
#
# Clave: (ticker_upper, ejercicio). Valor: PrecioHistorico.
# No persiste entre arranques; evita hits repetidos en la misma sesión.

_precio_cache: Dict[tuple, "PrecioHistorico"] = {}


# ── DATACLASS DE RESULTADO ─────────────────────────────────────────────────────

@dataclass
class PrecioHistorico:
    """
    Resultado de una consulta de precio histórico.

    ticker:       Ticker normalizado (uppercase). Ej. "BTC".
    ejercicio:    Año fiscal. Ej. 2024.
    fecha_corte:  Fecha usada para la consulta (31/12/ejercicio).
    precio_eur:   Precio en EUR a fecha_corte. None si no disponible.
    fuente:       FUENTE_* constante que identifica el origen del precio.
    estimado:     True si el precio es una aproximación (p.ej. type de cambio BCE).
    coingecko_id: ID CoinGecko usado, o None.
    nota:         Mensaje descriptivo para mostrar al usuario.
    """
    ticker:       str
    ejercicio:    int
    fecha_corte:  date
    precio_eur:   Optional[Decimal]
    fuente:       str
    estimado:     bool
    coingecko_id: Optional[str]
    nota:         str


# ── BCE: tipo de cambio EUR/USD ────────────────────────────────────────────────

def _bce_eurusd_historico(ejercicio: int) -> Optional[Decimal]:
    """
    Consulta el tipo de cambio EUR/USD oficial a 31/12 del ejercicio al BCE.

    El BCE publica tipos de cambio de referencia diarios. Si el 31/12 es
    festivo/fin de semana, retrocede hasta 5 días hábiles para encontrar
    la última cotización disponible.

    Returns: EUR por 1 USD (ej. Decimal("0.9201")), o None si falla.
    """
    # El BCE publica USD/EUR (cuántos USD por 1 EUR), nosotros necesitamos EUR/USD.
    # La serie EXR D.USD.EUR.SP00.A da USD por EUR → invertir para EUR por USD.
    for delta in range(6):
        d = date(ejercicio, 12, 31 - delta)
        fecha_str = d.strftime("%Y-%m-%d")
        url = (
            "https://data-api.ecb.europa.eu/service/data/"
            f"EXR/D.USD.EUR.SP00.A"
            f"?startPeriod={fecha_str}&endPeriod={fecha_str}&format=json"
        )
        try:
            resp = requests.get(url, timeout=_CG_TIMEOUT)
            if resp.status_code != 200:
                continue
            data = resp.json()
            obs = (
                data
                .get("dataSets", [{}])[0]
                .get("series", {})
                .get("0:0:0:0:0", {})
                .get("observations", {})
            )
            if not obs:
                continue
            # Tomar la primera (única) observación
            usd_per_eur = Decimal(str(list(obs.values())[0][0]))
            if usd_per_eur > 0:
                eur_per_usd = (Decimal("1") / usd_per_eur).quantize(
                    Decimal("0.000001"), rounding=ROUND_HALF_UP
                )
                logger.debug(
                    "BCE EUR/USD %s: 1 USD = %.6f EUR", fecha_str, eur_per_usd
                )
                return eur_per_usd
        except Exception as exc:
            logger.warning("BCE EUR/USD error (%s): %s", fecha_str, exc)
            continue
    return None


# ── COINGECKO: precio histórico ────────────────────────────────────────────────

def _coingecko_precio_eur(coingecko_id: str, fecha_cg: str) -> Optional[Decimal]:
    """
    Consulta el precio histórico de una moneda en CoinGecko.

    Args:
        coingecko_id: ID de CoinGecko (ej. "bitcoin").
        fecha_cg:     Fecha en formato DD-MM-YYYY (ej. "31-12-2024").

    Returns:
        Precio en EUR como Decimal, o None si falla / no hay datos.
    """
    url    = f"{_CG_BASE}/coins/{coingecko_id}/history"
    params = {"date": fecha_cg, "localization": "false"}
    headers = {}
    if _CG_API_KEY:
        headers["x-cg-pro-api-key"] = _CG_API_KEY

    try:
        resp = requests.get(url, params=params, headers=headers, timeout=_CG_TIMEOUT)
        if resp.status_code == 429:
            logger.warning("CoinGecko rate limit alcanzado para %s", coingecko_id)
            return None
        if resp.status_code != 200:
            logger.warning(
                "CoinGecko HTTP %d para %s @ %s", resp.status_code, coingecko_id, fecha_cg
            )
            return None
        data   = resp.json()
        precio = (
            data
            .get("market_data", {})
            .get("current_price", {})
            .get("eur")
        )
        if precio is None:
            logger.info("CoinGecko sin precio EUR para %s @ %s", coingecko_id, fecha_cg)
            return None
        return Decimal(str(precio)).quantize(
            Decimal("0.000001"), rounding=ROUND_HALF_UP
        )
    except Exception as exc:
        logger.warning("CoinGecko error para %s @ %s: %s", coingecko_id, fecha_cg, exc)
        return None


# ── FUNCIÓN PRINCIPAL: un ticker ───────────────────────────────────────────────

def obtener_precio_historico(ticker: str, ejercicio: int) -> PrecioHistorico:
    """
    Devuelve el precio en EUR de `ticker` a 31/12/`ejercicio`.

    Orden de resolución:
      1. Stablecoins USD → tipo de cambio BCE (estimado).
      2. CoinGecko si el ticker tiene ID registrado.
      3. No disponible.

    Usa caché en memoria para evitar requests duplicados en la misma sesión.
    """
    ticker_up = ticker.upper()
    cache_key = (ticker_up, ejercicio)

    if cache_key in _precio_cache:
        return _precio_cache[cache_key]

    fecha_corte = date(ejercicio, 12, 31)
    hoy         = date.today()

    # ── Fecha futura ────────────────────────────────────────────────────────
    if fecha_corte > hoy:
        resultado = PrecioHistorico(
            ticker       = ticker_up,
            ejercicio    = ejercicio,
            fecha_corte  = fecha_corte,
            precio_eur   = None,
            fuente       = FUENTE_FECHA_FUTURA,
            estimado     = False,
            coingecko_id = None,
            nota         = (
                f"La fecha 31/12/{ejercicio} es futura. "
                "El precio de cierre no está disponible todavía."
            ),
        )
        _precio_cache[cache_key] = resultado
        return resultado

    fecha_cg = fecha_corte.strftime("%d-%m-%Y")  # DD-MM-YYYY para CoinGecko

    # ── 1. Stablecoins USD → BCE ─────────────────────────────────────────────
    if ticker_up in _STABLECOINS_USD:
        eur_per_usd = _bce_eurusd_historico(ejercicio)
        if eur_per_usd is not None:
            resultado = PrecioHistorico(
                ticker       = ticker_up,
                ejercicio    = ejercicio,
                fecha_corte  = fecha_corte,
                precio_eur   = eur_per_usd,
                fuente       = FUENTE_ESTIMADO_BCE,
                estimado     = True,
                coingecko_id = None,
                nota         = (
                    f"Stablecoin USD. Valor EUR estimado: tipo de cambio BCE "
                    f"EUR/USD a 31/12/{ejercicio} = {eur_per_usd} EUR por USD. "
                    "OrigenValorMonedas: O (valoración propia)."
                ),
            )
        else:
            resultado = PrecioHistorico(
                ticker       = ticker_up,
                ejercicio    = ejercicio,
                fecha_corte  = fecha_corte,
                precio_eur   = None,
                fuente       = FUENTE_NO_DISPONIBLE,
                estimado     = False,
                coingecko_id = None,
                nota         = (
                    f"Stablecoin USD. No se pudo obtener el tipo de cambio BCE "
                    f"EUR/USD a 31/12/{ejercicio}. Actualizar manualmente."
                ),
            )
        _precio_cache[cache_key] = resultado
        return resultado

    # ── 2. CoinGecko ────────────────────────────────────────────────────────
    cg_id = COINGECKO_IDS.get(ticker_up)
    if cg_id:
        precio = _coingecko_precio_eur(cg_id, fecha_cg)
        if precio is not None:
            resultado = PrecioHistorico(
                ticker       = ticker_up,
                ejercicio    = ejercicio,
                fecha_corte  = fecha_corte,
                precio_eur   = precio,
                fuente       = FUENTE_COINGECKO,
                estimado     = False,
                coingecko_id = cg_id,
                nota         = (
                    f"Precio CoinGecko a 31/12/{ejercicio}: {precio} EUR. "
                    "Fuente: CoinGecko History API. "
                    "OrigenValorMonedas: O (valoración propia)."
                ),
            )
        else:
            resultado = PrecioHistorico(
                ticker       = ticker_up,
                ejercicio    = ejercicio,
                fecha_corte  = fecha_corte,
                precio_eur   = None,
                fuente       = FUENTE_NO_DISPONIBLE,
                estimado     = False,
                coingecko_id = cg_id,
                nota         = (
                    f"CoinGecko no devolvió precio EUR para '{ticker_up}' "
                    f"a 31/12/{ejercicio}. Actualizar manualmente."
                ),
            )
        _precio_cache[cache_key] = resultado
        return resultado

    # ── 3. No disponible ────────────────────────────────────────────────────
    resultado = PrecioHistorico(
        ticker       = ticker_up,
        ejercicio    = ejercicio,
        fecha_corte  = fecha_corte,
        precio_eur   = None,
        fuente       = FUENTE_NO_DISPONIBLE,
        estimado     = False,
        coingecko_id = None,
        nota         = (
            f"'{ticker_up}' no encontrado en el catálogo de CoinGecko. "
            "Buscar el ID manualmente en coingecko.com y actualizar COINGECKO_IDS, "
            "o introducir el precio manualmente."
        ),
    )
    _precio_cache[cache_key] = resultado
    return resultado


# ── FUNCIÓN BATCH: múltiples tickers ──────────────────────────────────────────

def obtener_precios_historicos(
    tickers: List[str],
    ejercicio: int,
) -> Dict[str, PrecioHistorico]:
    """
    Obtiene precios históricos para una lista de tickers.

    Aplica un throttle de _CG_THROTTLE segundos entre requests a CoinGecko
    para respetar el rate limit del tier gratuito (~30 req/min).
    Los resultados de caché no generan espera.

    Args:
        tickers:   Lista de tickers (ej. ["BTC", "ETH", "USDT"]).
        ejercicio: Año fiscal (ej. 2024).

    Returns:
        Dict con ticker (uppercase) → PrecioHistorico.
    """
    resultado: Dict[str, PrecioHistorico] = {}
    _ultima_peticion_cg: float = 0.0

    for ticker in tickers:
        ticker_up = ticker.upper()
        cache_key = (ticker_up, ejercicio)

        if cache_key in _precio_cache:
            resultado[ticker_up] = _precio_cache[cache_key]
            continue

        # Throttle solo para CoinGecko (BCE también lo aplicamos por seguridad)
        es_stablecoin = ticker_up in _STABLECOINS_USD
        necesita_http  = (
            not es_stablecoin and ticker_up in COINGECKO_IDS
        ) or es_stablecoin

        if necesita_http:
            elapsed = time.monotonic() - _ultima_peticion_cg
            if elapsed < _CG_THROTTLE:
                time.sleep(_CG_THROTTLE - elapsed)

        ph = obtener_precio_historico(ticker_up, ejercicio)
        resultado[ticker_up] = ph
        _ultima_peticion_cg = time.monotonic()

    return resultado


# ── ENRIQUECIMIENTO DEL JSON 721 ───────────────────────────────────────────────

def enriquecer_721_con_precios(
    datos: dict,
    precios: Dict[str, "PrecioHistorico"],
) -> dict:
    """
    Enriquece el JSON del Modelo 721 con los precios históricos obtenidos.

    Para cada activo en datos["exchanges"][*]["activos"]:
      - Si hay precio disponible: rellena valor_eur, origen_valor="O",
        sustituye advertencias de precio pendiente por nota de trazabilidad.
      - Si no hay precio: mantiene valor_eur=None, añade nota informativa.

    Recalcula total_valor_eur si todos los activos tienen precio.

    Args:
        datos:   Dict resultado de generar_datos_modelo_721().
        precios: Dict (ticker_upper → PrecioHistorico) de obtener_precios_historicos().

    Returns:
        Copia del dict enriquecido. No muta el argumento original.
    """
    import copy
    datos = copy.deepcopy(datos)

    total_eur    = Decimal("0")
    todo_con_precio = True

    for exc in datos.get("exchanges", []):
        for activo in exc.get("activos", []):
            ticker = activo["activo"].upper()
            ph     = precios.get(ticker)

            if ph is None or ph.precio_eur is None:
                todo_con_precio = False
                # Mantener advertencia original o añadir nota de fallo
                if ph is not None:
                    _reemplazar_advertencias_precio(activo, ticker, ph.nota)
                continue

            # Calcular valor EUR = precio * cantidad
            cantidad  = Decimal(activo["cantidad"])
            valor_eur = (ph.precio_eur * cantidad).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )

            activo["valor_eur"]    = str(valor_eur)
            activo["origen_valor"] = "O"   # OrigenValorMonedas: O = valoración propia

            # Sustituir advertencias de precio-pendiente por nota de trazabilidad
            _reemplazar_advertencias_precio(activo, ticker, ph.nota)

            total_eur += valor_eur

    if todo_con_precio and total_eur > 0:
        datos["total_valor_eur"] = str(
            total_eur.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        )

    return datos


def _reemplazar_advertencias_precio(activo: dict, ticker: str, nota_nueva: str) -> None:
    """
    Filtra las advertencias genéricas de precio-pendiente del array de advertencias
    del activo y añade la nota de trazabilidad de la fuente usada.
    """
    advertencias_orig = activo.get("advertencias", [])
    advertencias_filtradas = [
        adv for adv in advertencias_orig
        if not any(frag in adv for frag in _ADV_PRECIO_PENDIENTE)
    ]
    advertencias_filtradas.append(nota_nueva)
    activo["advertencias"] = advertencias_filtradas
