"""Recuperación OPCIONAL de ejecuciones Spot con API de Binance de SOLO LECTURA.

No almacena credenciales ni datos en BD; solo consultas GET a endpoint fijo
de Binance. Retorna CSV originalizable para el importador multifuente.
No reconstruye por sí solo todos los productos ni un FIFO fiscal válido.
"""
from __future__ import annotations

import csv
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import hmac
import io
import json
import re
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

_BASE = "https://api.binance.com"
_SYMBOL = re.compile(r"^[A-Z0-9]{5,20}$")
_PAGE = 1000
_MAX_PAGES = 5


class BinanceApiRecoveryError(ValueError):
    """Mensaje controlado para el usuario, sin credenciales ni transacciones."""


def _positive_decimal(value, field: str, *, allow_zero: bool = False) -> str:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise BinanceApiRecoveryError("Binance devolvió cantidades o precios inválidos.") from exc
    if not number.is_finite() or number < 0 or (number == 0 and not allow_zero):
        raise BinanceApiRecoveryError("Binance devolvió cantidades o precios inválidos.")
    # Evitar notación exponencial: el CSV nativo acepta decimales ordinarios.
    return format(number, "f")


class _NoRedirect(HTTPRedirectHandler):
    """No reenviar encabezados de API a otro host por una redirección."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise BinanceApiRecoveryError("Binance ha redirigido la consulta API.")


class BinanceReadOnlySpot:
    """API acotada: no permite crear órdenes, transferencias o retiradas."""

    def __init__(self, key: str, secret: str, *, transport=None, now_ms=None):
        if not isinstance(key, str) or not isinstance(secret, str):
            raise BinanceApiRecoveryError("Credenciales API inválidas.")
        if (not 16 <= len(key) <= 200 or not 16 <= len(secret) <= 200
                or any(ch.isspace() for ch in key + secret)):
            raise BinanceApiRecoveryError("Credenciales API inválidas.")
        self._key = key
        self._secret = secret.encode("utf-8")
        self._transport = transport or self._urllib_transport
        self._now_ms = now_ms or (lambda: int(time.time() * 1000))

    @staticmethod
    def _urllib_transport(url: str, headers: dict) -> dict:
        request = Request(url, headers=headers, method="GET")
        try:
            with build_opener(_NoRedirect()).open(request, timeout=8) as response:
                data = response.read(3 * 1024 * 1024 + 1)
                if len(data) > 3 * 1024 * 1024:
                    raise BinanceApiRecoveryError("Respuesta Binance demasiado extensa.")
                return json.loads(data.decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, UnicodeDecodeError,
                json.JSONDecodeError) as exc:
            # NO incluir URLs firmadas ni mensajes remotos en logs/respuestas.
            raise BinanceApiRecoveryError(
                "Binance no ha permitido consultar la API. Comprueba la "
                "clave de solo lectura, su configuración IP y los límites."
            ) from exc

    def _get(self, path: str, parameters: dict | None = None, *, signed=False):
        if path not in (
            "/sapi/v1/account/apiRestrictions",
            "/api/v3/exchangeInfo",
            "/api/v3/myTrades",
        ):
            raise BinanceApiRecoveryError("Consulta API no permitida.")
        params = dict(parameters or {})
        headers = {}
        if signed:
            params["timestamp"] = self._now_ms()
            params["recvWindow"] = 5000
            unsigned = urlencode(params)
            params["signature"] = hmac.new(
                self._secret, unsigned.encode(), hashlib.sha256
            ).hexdigest()
            headers["X-MBX-APIKEY"] = self._key
        response = self._transport(_BASE + path + "?" + urlencode(params), headers)
        if isinstance(response, dict) and ("code" in response and "msg" in response):
            raise BinanceApiRecoveryError(
                "La API de Binance ha rechazado la consulta de lectura."
            )
        return response

    def verify_read_only(self):
        permissions = self._get("/sapi/v1/account/apiRestrictions", signed=True)
        if not isinstance(permissions, dict) or permissions.get("enableReading") is not True:
            raise BinanceApiRecoveryError("La API no acredita permiso de solo lectura.")
        # Rechazar cualquier permiso habilitado distinto del de lectura.
        for name, enabled in permissions.items():
            if (name.startswith("enable") and name != "enableReading"
                    and enabled is not False):
                raise BinanceApiRecoveryError(
                    "La clave API tiene permisos adicionales. Crea una "
                    "Tax Report API exclusivamente de lectura."
                )

    def _pair(self, symbol: str) -> tuple[str, str]:
        response = self._get("/api/v3/exchangeInfo", {"symbol": symbol})
        symbols = response.get("symbols") if isinstance(response, dict) else None
        if not isinstance(symbols, list) or len(symbols) != 1:
            raise BinanceApiRecoveryError("Par Spot no reconocido por Binance.")
        item = symbols[0]
        base, quote = item.get("baseAsset"), item.get("quoteAsset")
        if (item.get("symbol") != symbol
                or not all(isinstance(a, str) and re.fullmatch(r"[A-Z0-9]{2,20}", a)
                           for a in (base, quote))):
            raise BinanceApiRecoveryError("Metadatos del par Spot inválidos.")
        return base, quote

    def retrieve(self, symbol: str, *, from_id: int = 0):
        if not isinstance(symbol, str) or not _SYMBOL.fullmatch(symbol):
            raise BinanceApiRecoveryError("Introduce un par Spot válido, por ejemplo BTCUSDT.")
        if type(from_id) is not int or not 0 <= from_id < 10**20:
            raise BinanceApiRecoveryError("Identificador de inicio inválido.")

        self.verify_read_only()
        base, quote = self._pair(symbol)
        cursor = from_id
        collected = []
        seen = set()
        more = False
        for _ in range(_MAX_PAGES):
            rows = self._get("/api/v3/myTrades", {
                "symbol": symbol, "fromId": cursor, "limit": _PAGE,
            }, signed=True)
            if not isinstance(rows, list) or len(rows) > _PAGE:
                raise BinanceApiRecoveryError("Formato de operaciones Spot inesperado.")
            if not rows:
                more = False
                break
            for trade in rows:
                if not isinstance(trade, dict) or trade.get("symbol", symbol) != symbol:
                    raise BinanceApiRecoveryError("Identidad Spot inválida.")
                tid = trade.get("id")
                orderid = trade.get("orderId")
                epoch = trade.get("time")
                if (type(tid) is not int or tid < cursor or tid in seen
                        or type(orderid) is not int or orderid < 0
                        or type(epoch) is not int or epoch < 0):
                    raise BinanceApiRecoveryError("Secuencia Spot no verificable.")
                seen.add(tid)
                if type(trade.get("isBuyer")) is not bool:
                    raise BinanceApiRecoveryError("Lado de operación no verificable.")
                fee_asset = trade.get("commissionAsset", "")
                if not isinstance(fee_asset, str) or not re.fullmatch(
                    r"[A-Z0-9]{2,20}", fee_asset
                ):
                    raise BinanceApiRecoveryError("Activo de comisión inválido.")
                try:
                    at = datetime.fromtimestamp(epoch / 1000, timezone.utc)
                except (OverflowError, ValueError, OSError) as exc:
                    raise BinanceApiRecoveryError("Fecha Spot inválida.") from exc
                price = _positive_decimal(trade.get("price"), "price")
                qty = _positive_decimal(trade.get("qty"), "qty")
                quoteqty = _positive_decimal(trade.get("quoteQty"), "quoteQty")
                commission = _positive_decimal(
                    trade.get("commission"), "commission", allow_zero=True
                )
                collected.append((
                    orderid,
                    at.strftime("%Y-%m-%d %H:%M:%S"),
                    symbol,
                    "BUY" if trade["isBuyer"] else "SELL",
                    price,
                    qty + base,
                    quoteqty + quote,
                    commission + fee_asset,
                    "", "", tid, epoch,
                ))
            highest = max(seen)
            if highest < cursor:
                raise BinanceApiRecoveryError("Cursor Spot inválido.")
            cursor = highest + 1
            if len(rows) < _PAGE:
                more = False
                break
            more = True
        # El indicador de continuación es conservador incluso si son exactamente N filas.
        if not collected:
            raise BinanceApiRecoveryError(
                "La API no ha devuelto ejecuciones Spot para ese par."
            )
        content = io.StringIO(newline="")
        writer = csv.writer(content)
        writer.writerow([
            "Número de pedido", "Tiempo", "Par", "Lado", "Precio",
            "Ejecutado", "Cantidad", "Tarifa",
            "Par de conversión de AOR", "Tasa de conversión de AOR",
            "ID de ejecución API", "Tiempo unix ms API",
        ])
        writer.writerows(collected)
        return {
            "csv": content.getvalue().encode("utf-8-sig"),
            "next_id": cursor,
            "has_more": more,
            "records": len(collected),
            "symbol": symbol,
        }
