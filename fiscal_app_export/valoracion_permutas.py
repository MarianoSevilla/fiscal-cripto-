"""Valoración documentada de permutas para IRPF (art. 37.1.h LIRPF).

Nunca usa coste de adquisición como proxy de valor de mercado.
Cada pierna precisa un precio EUR con marca de tiempo aceptable. CoinGecko
puede no suministrar datos horarios históricos en todos los planes; en ese
caso el informe debe quedar pendiente, nunca inventarse cotizaciones.
Este módulo NO se utiliza para Modelo 721.
"""
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from decimal import Decimal, InvalidOperation
import logging
import math
import os

import requests

from precios_historicos import COINGECKO_IDS

logger = logging.getLogger(__name__)

# Historical points sampled >30 min away may be very different for volatile
# crypto-assets. Record the actual timestamp; never accept daily proxy prices.
_MAX_DISTANCE_SECONDS = 30 * 60
_MAX_REQUESTS = 8
_TIMEOUT_SECONDS = 2.5
_BASE = "https://pro-api.coingecko.com/api/v3" if os.getenv("COINGECKO_API_KEY") else "https://api.coingecko.com/api/v3"


@dataclass(frozen=True)
class CotizacionEUR:
    valor_eur: Decimal
    fuente: str
    fecha_fuente_utc: datetime


@dataclass(frozen=True)
class PermutaValorada:
    valor_entregado_eur: Decimal
    valor_recibido_eur: Decimal
    fuente_entregado: str
    fuente_recibido: str
    fecha_entregado_utc: datetime
    fecha_recibido_utc: datetime

    @property
    def valor_transmision_eur(self) -> Decimal:
        return max(self.valor_entregado_eur, self.valor_recibido_eur)

    def detalle(self, entregado: str, recibido: str) -> str:
        return (
            f"PERMUTA {entregado}/{recibido}: mercado EUR entregado "
            f"{self.valor_entregado_eur} ({self.fuente_entregado}, "
            f"{self.fecha_entregado_utc.isoformat()}), recibido "
            f"{self.valor_recibido_eur} ({self.fuente_recibido}, "
            f"{self.fecha_recibido_utc.isoformat()}); "
            f"base fiscal EUR {self.valor_transmision_eur}."
        )


def _decimal_positivo(v) -> Decimal:
    try:
        d = Decimal(str(v))
        if d.is_finite() and d > 0 and math.isfinite(float(d)):
            return d
    except (TypeError, ValueError, OverflowError, InvalidOperation):
        pass
    raise ValueError("Datos fiscales no seguros: valoración de mercado EUR inválida.")


def _fecha_utc(s: str) -> datetime:
    try:
        dt = datetime.fromisoformat(str(s).strip().replace("Z", "+00:00"))
    except (ValueError, TypeError):
        raise ValueError(
            "Datos fiscales no seguros: fecha/hora de permuta inválida para consultar precios."
        ) from None
    # Parser CSV UTC; offsets explicitly supplied are converted to UTC.
    return (dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None
            else dt.astimezone(timezone.utc))


class ValoradorPermutasEUR:
    """Resuelve únicamente cotizaciones referidas a la fecha de la operación.

    Cache por fecha-hora y moneda limitado a esta solicitud; no persiste ni
    comparte datos personales, y no hace peticiones sin identificador conocido.
    """
    def __init__(self, *, http_get=None):
        self.http_get = http_get or requests.get
        self.cache = {}
        self.requests = 0

    def precio(self, ticker: str, fecha: datetime) -> CotizacionEUR | None:
        ticker = str(ticker).upper().strip()
        cg_id = COINGECKO_IDS.get(ticker)
        if not cg_id:
            return None
        cache_key = (cg_id, fecha.replace(minute=0, second=0, microsecond=0))
        if cache_key not in self.cache:
            if self.requests >= _MAX_REQUESTS:
                return None
            self.requests += 1
            unix = int(fecha.timestamp())
            key = os.getenv("COINGECKO_API_KEY", "")
            headers = {"x-cg-pro-api-key": key} if key else {}
            try:
                response = self.http_get(
                    f"{_BASE}/coins/{cg_id}/market_chart/range",
                    params={"vs_currency": "eur", "from": unix - 3600,
                            "to": unix + 3600},
                    headers=headers, timeout=_TIMEOUT_SECONDS,
                )
                if response.status_code != 200:
                    logger.info("No hay precio histórico fiable para %s: HTTP %s", cg_id, response.status_code)
                    self.cache[cache_key] = ()
                else:
                    values = response.json().get("prices", [])
                    if not isinstance(values, list) or len(values) > 1000:
                        values = []
                    prices = []
                    for point in values:
                        if not isinstance(point, (list, tuple)) or len(point) < 2:
                            continue
                        try:
                            t = datetime.fromtimestamp(float(point[0]) / 1000, tz=timezone.utc)
                            p = _decimal_positivo(point[1])
                            prices.append((t, p))
                        except (ValueError, OSError, OverflowError):
                            continue
                    self.cache[cache_key] = tuple(prices)
            except (requests.RequestException, ValueError, TypeError, KeyError, AttributeError) as exc:
                logger.info("Fallo de precio histórico %s: %s", cg_id, type(exc).__name__)
                self.cache[cache_key] = ()
        values = self.cache[cache_key]
        if not values:
            return None
        t, price = min(values, key=lambda x: abs((x[0] - fecha).total_seconds()))
        if abs((t - fecha).total_seconds()) > _MAX_DISTANCE_SECONDS:
            return None
        return CotizacionEUR(price, f"CoinGecko/{cg_id}", t)

    def resolver(self, swap, clasificador) -> PermutaValorada:
        fecha = _fecha_utc(getattr(swap, "fecha", None))
        ent = str(swap.activo_entregado).upper().strip()
        rec = str(swap.activo_recibido).upper().strip()
        if not ent or not rec or ent == rec:
            raise ValueError("Datos fiscales no seguros: permuta sin dos activos distintos.")

        # R01: valor de mercado de ambas patas, no una aproximación basada
        # en subtotal del CSV. El campo Coinbase "Subtotal" está denominado
        # en EUR, pero NO identifica de forma inequívoca el mercado del activo
        # recibido. Kraken tampoco acredita la frescura de su precio cercano.
        # Hasta verificar documentalmente su procedencia, ninguna de esas
        # cifras sustituye una cotización de ambas patas en el instante.
        quoted_ent = self.precio(ent, fecha)
        quoted_rec = self.precio(rec, fecha)
        if quoted_ent is None or quoted_rec is None:
            missing = ", ".join(
                [name for name, quote in ((ent, quoted_ent), (rec, quoted_rec))
                 if quote is None]
            )
            raise ValueError(
                f"Datos fiscales no seguros: faltan cotizaciones históricas EUR "
                f"válidas para {missing} en la permuta del {fecha.isoformat()}. "
                "La operación requiere valoración documentada antes de generar PDF."
            )
        qty_ent = _decimal_positivo(swap.cantidad_entregada)
        qty_rec = _decimal_positivo(swap.cantidad_recibida)
        # Ambos precios corresponden a EUR por unidad del activo.
        total_ent = quoted_ent.valor_eur * qty_ent
        total_rec = quoted_rec.valor_eur * qty_rec
        _decimal_positivo(total_ent)
        _decimal_positivo(total_rec)
        return PermutaValorada(
            total_ent, total_rec, quoted_ent.fuente, quoted_rec.fuente,
            quoted_ent.fecha_fuente_utc, quoted_rec.fecha_fuente_utc,
        )
