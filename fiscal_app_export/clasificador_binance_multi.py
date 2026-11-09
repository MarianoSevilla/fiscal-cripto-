"""
Importador fiscal Binance multifuente.

Normaliza exportaciones nativas de Binance (Spot, Convert, fiat, depósitos /
retiros y Transaction History) a las estructuras canónicas que consume
MotorFIFO. Las fuentes se detectan por cabecera y contenido, nunca por nombre.

Principios:
- Spot operations (fills) manda sobre Spot orders.
- Convert orders manda sobre eventos Convert del Transaction History.
- compras/ventas fiat nativas mandan sobre equivalentes del Transaction History.
- depósitos/retiros específicos mandan sobre movimientos duplicados del ledger.
- cualquier hecho material no interpretado, valoración EUR pendiente o comisión
  sin tratamiento verificable queda explícito para que la aceptación fiscal
  falle cerrada. Nunca se asume USDT/USDC == EUR ni coste cero.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import tempfile
import unicodedata
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from clasificador import (
    OperacionCompraventa,
    OperacionSwap,
    OperacionRendimiento,
    OperacionMovimiento,
    OperacionDesconocida,
)
from clasificador_binance_tx import REGLAS_TX


_NO_DATA = "no hay datos que se ajusten a los criterios"
_SUCCESS = {"successful", "completed", "success"}

_TRADELIKE_TX = {
    "Transaction Buy", "Transaction Spend", "Transaction Fee",
    "Transaction Sold", "Transaction Revenue",
    "Binance Convert", "Buy Crypto With Fiat", "Sell Crypto To Fiat",
}
_CRYPTO_TRANSFER_TX = {"Deposit", "Withdraw"}
_FIAT_TRANSFER_TX = {"Fiat Deposit", "Fiat Withdraw"}


class BinanceMultiUserError(ValueError):
    """Error de formato/selección de ficheros listo para mostrar al usuario."""

    def __init__(self, code: str, message: str, category: str = "user_error"):
        super().__init__(message)
        self.code = code
        self.category = category


@dataclass
class _Section:
    detectado: bool = False
    vacio: bool = False
    registros: int = 0

    def as_dict(self) -> dict:
        return {
            "detectado": self.detectado,
            "vacio": self.vacio,
            "registros": self.registros,
        }


@dataclass(frozen=True)
class BinanceNativeExchange:
    """Hecho económico original, sin valorar ni fusionar por segundo.

    Se conserva exclusivamente durante la petición; no contiene cuentas,
    identificadores de usuario ni movimientos privados en logs persistentes.
    """
    source: str
    filename: str
    local_time: str
    given_asset: str
    given_amount: Decimal
    received_asset: str
    received_amount: Decimal
    fee_asset: Optional[str]
    fee_amount: Decimal
    payment_method: str = ""


_HEADER_ALIASES = {
    # Transaction History clásico / variante 2026 (PR #192)
    "hora": "tiempo",
    "cambiar": "cambio",
    "comentario": "observación",
    "user id": "id de usuario",
    "time": "tiempo",
    "account": "cuenta",
    "operation": "operación",
    "coin": "moneda",
    "change": "cambio",
    "remark": "observación",
}


def _norm_header(value: str) -> str:
    # Quitar notas tipográficas ANTES de NFKC: NFKC transforma ¹/²/³ en
    # dígitos ASCII y haría irreconocibles cabeceras como "Total de trading³".
    value = re.sub(r"[¹²³⁴⁵⁶⁷⁸⁹⁰]+$", "", str(value or "").strip())
    value = unicodedata.normalize("NFKC", value)
    value = value.lstrip("\ufeff").strip().lower()
    value = " ".join(value.split())
    return _HEADER_ALIASES.get(value, value)


def _read_csv(path: str) -> Tuple[List[str], List[dict], bool]:
    with open(path, "r", encoding="utf-8-sig", errors="replace", newline="") as fh:
        reader = csv.reader(fh)
        try:
            headers = next(reader)
        except StopIteration:
            return [], [], True
        keys = [_norm_header(h) for h in headers]
        if not keys or any(not key for key in keys):
            raise BinanceMultiUserError(
                "invalid_csv_headers",
                "Binance contiene una cabecera CSV vacía o inválida.",
                category="parser_error",
            )
        duplicate_keys = {key for key in keys if keys.count(key) > 1}
        # El historial oficial de órdenes Spot trae dos columnas Tiempo.
        # El cálculo FIFO no utiliza ninguna de sus fechas para crear
        # ejecuciones. Para otros formatos, el dict sobreescribiría datos
        # normalizados sin avisar (por ejemplo, Hora y Tiempo).
        expected_spot_orders = {
            "número de pedido", "par", "lado", "precio de la orden",
            "cantidad de la orden", "precio medio", "total de trading", "estado",
        }
        spot_orders_double_time = (
            duplicate_keys == {"tiempo"}
            and keys.count("tiempo") == 2
            and expected_spot_orders.issubset(set(keys))
        )
        if duplicate_keys and not spot_orders_double_time:
            raise BinanceMultiUserError(
                "ambiguous_csv_headers",
                "Binance contiene columnas duplicadas después de normalizar "
                "las cabeceras. No se puede interpretar sin perder datos.",
                category="parser_error",
            )
        rows: List[dict] = []
        sentinel = False
        for raw in reader:
            if not any((c or "").strip() for c in raw):
                continue
            first = (raw[0] or "").strip().lower()
            if _NO_DATA in first:
                sentinel = True
                continue
            if len(raw) != len(keys):
                raise BinanceMultiUserError(
                    "inconsistent_csv_columns",
                    "Binance contiene filas con un número de columnas distinto "
                    "al de la cabecera. No es seguro interpretar ese CSV.",
                    category="parser_error",
                )
            row = {k: raw[i].strip() for i, k in enumerate(keys)}
            rows.append(row)
    return headers, rows, (sentinel or not rows)


_SIG = {
    "transaction_history": {"tiempo", "cuenta", "operación", "moneda", "cambio"},
    "spot_trades": {"número de pedido", "tiempo", "par", "lado", "precio",
                    "ejecutado", "cantidad", "tarifa"},
    "spot_orders": {"número de pedido", "par", "lado", "precio de la orden",
                    "cantidad de la orden", "precio medio", "total de trading", "estado"},
    "convert_orders": {"tiempo", "billetera", "par", "tipo", "vender", "comprar",
                       "precio", "estado"},
    "recurring_convert": {"momento de creación", "billetera", "frecuencia",
                          "importe de origen", "moneda de origen",
                          "importe de destino", "moneda de destino", "estado"},
    "fiat_trade": {"tiempo", "método", "cantidad a gastar", "recibir cantidad",
                   "tarifa", "precio", "estado", "id de transacción"},
    "fiat_deposit": {"tiempo", "método", "importe de depósito", "recibir cantidad",
                     "tarifa", "estado", "id de transacción"},
    "fiat_withdrawal": {"tiempo", "método", "importe de retiro", "recibir cantidad",
                        "tarifa", "estado", "id de transacción"},
    "fiat_exchange": {"método", "cantidad", "precio", "cantidad final",
                      "hora de creación", "estado", "id de transacción"},
    "crypto_transfer": {"tiempo", "moneda", "red", "cantidad", "dirección", "txid", "estado"},
}


def detect_binance_source(headers: Iterable[str]) -> str:
    norm = {_norm_header(h) for h in headers}
    if _SIG["spot_orders"].issubset(norm):
        return "spot_orders"
    if _SIG["spot_trades"].issubset(norm):
        return "spot_trades"
    if _SIG["convert_orders"].issubset(norm):
        return "convert_orders"
    if _SIG["recurring_convert"].issubset(norm):
        return "recurring_convert"
    if _SIG["fiat_deposit"].issubset(norm):
        return "fiat_deposit"
    if _SIG["fiat_withdrawal"].issubset(norm):
        return "fiat_withdrawal"
    if _SIG["fiat_exchange"].issubset(norm):
        return "fiat_exchange"
    if _SIG["fiat_trade"].issubset(norm):
        return "fiat_trade"
    if _SIG["transaction_history"].issubset(norm):
        return "transaction_history"
    if _SIG["crypto_transfer"].issubset(norm):
        return "crypto_withdrawal" if "tarifa" in norm else "crypto_deposit"
    return "unknown"


_AMOUNT_ASSET = re.compile(
    r"^\s*([+-]?(?:\d+(?:\.\d+)?|\.\d+))\s*([A-Za-z0-9._-]+)\s*$"
)


def _amount_asset(raw: str, *, field: str) -> Tuple[Decimal, str]:
    m = _AMOUNT_ASSET.match(str(raw or ""))
    if not m:
        raise BinanceMultiUserError(
            "invalid_amount_asset",
            f"Binance contiene un valor no interpretable en «{field}». "
            "Descarga de nuevo los archivos sin modificarlos.",
            category="parser_error",
        )
    try:
        amount = Decimal(m.group(1))
    except InvalidOperation as exc:
        raise BinanceMultiUserError(
            "invalid_decimal",
            f"Binance contiene una cantidad inválida en «{field}».",
            category="parser_error",
        ) from exc
    if not amount.is_finite():
        raise BinanceMultiUserError(
            "nonfinite_decimal",
            f"Binance contiene una cantidad no finita en «{field}».",
            category="parser_error",
        )
    return amount, m.group(2).upper()


def _decimal(raw: str, *, field: str) -> Decimal:
    try:
        value = Decimal(str(raw or "").strip())
    except InvalidOperation as exc:
        raise BinanceMultiUserError(
            "invalid_decimal",
            f"Binance contiene una cantidad inválida en «{field}».",
            category="parser_error",
        ) from exc
    if not value.is_finite():
        raise BinanceMultiUserError(
            "nonfinite_decimal",
            f"Binance contiene una cantidad no finita en «{field}».",
            category="parser_error",
        )
    return value


def _fecha(raw: str) -> str:
    raw = str(raw or "").strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%y-%m-%d %H:%M:%S", "%Y-%m-%d", "%y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
    raise BinanceMultiUserError(
        "invalid_date",
        "Binance contiene una fecha que no se puede interpretar. "
        "Descarga de nuevo el historial sin modificarlo.",
        category="parser_error",
    )


def _status_ok(raw: str) -> bool:
    return str(raw or "").strip().lower() in _SUCCESS


def _row_digest(source: str, row: dict) -> str:
    payload = json.dumps([source, sorted(row.items())], ensure_ascii=False,
                         separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _tz_from_filename(name: str) -> Optional[str]:
    m = re.search(r"\(UTC([+-]\d{1,2})(?::(\d{2}))?\)", str(name or ""), re.I)
    if not m:
        return None
    minutes = m.group(2) or "00"
    return f"UTC{int(m.group(1)):+d}:{minutes}"


class ClasificadorBinanceMulti:
    """Agrega múltiples exportaciones Binance sin duplicar fuentes económicas."""

    SOURCE_KEYS = (
        "spot_trades", "spot_orders", "convert_orders", "recurring_convert",
        "fiat_trade", "fiat_deposit", "fiat_withdrawal", "fiat_exchange",
        "crypto_deposit", "crypto_withdrawal", "transaction_history",
    )

    def __init__(self, filepaths: List[str], filenames: Optional[List[str]] = None):
        self.filepaths = list(filepaths)
        self.filenames = list(filenames) if filenames else [Path(p).name for p in filepaths]
        if len(self.filepaths) != len(self.filenames):
            raise ValueError("filepaths y filenames deben tener la misma longitud")

        self.compraventas: List[OperacionCompraventa] = []
        self.swaps: List[OperacionSwap] = []
        self.rendimientos: List[OperacionRendimiento] = []
        self.movimientos: List[OperacionMovimiento] = []
        self.desconocidas: List[OperacionDesconocida] = []
        self.advertencias: List[str] = []

        self.valoraciones_pendientes: List[dict] = []
        self.comisiones_pendientes: List[dict] = []
        self.intercambios_nativos: List[BinanceNativeExchange] = []
        self.fuentes_materiales_no_soportadas: List[str] = []
        self._sections: Dict[str, _Section] = {k: _Section() for k in self.SOURCE_KEYS}
        self._unknown_files = 0
        self._source_rows: Dict[str, List[Tuple[dict, str]]] = {k: [] for k in self.SOURCE_KEYS}
        self._cross_file_rows: Dict[str, str] = {}
        self._tz_offsets: set[str] = set()

        # Identidad económica de fuentes nativas. Se usa exclusivamente para
        # reconciliar Transaction History; nunca para fabricar operaciones.
        # key = (source_group, fecha, give_asset, recv_asset)
        # value = [give_total, recv_total]
        self._native_exchange_totals: Dict[tuple, List[Decimal]] = {}
        self._native_exchange_fee_totals: Dict[tuple, Dict[str, Decimal]] = {}
        # El mismo activo/importe/segundo puede representar más de un evento:
        # una clave de conjunto no acredita una deduplicación uno-a-uno.
        self._native_transfer_keys: Dict[tuple, int] = {}
        self._native_cash_keys: Dict[tuple, int] = {}

    @property
    def resumen_archivos(self) -> dict:
        out = {k: v.as_dict() for k, v in self._sections.items()}
        out["no_reconocidos"] = self._unknown_files
        out["timezone_offsets"] = sorted(self._tz_offsets)
        return out

    def clasificar(self) -> "ClasificadorBinanceMulti":
        if not self.filepaths:
            raise BinanceMultiUserError("no_files", "No se recibió ningún archivo de Binance.")

        recognized = 0
        for path, filename in zip(self.filepaths, self.filenames):
            headers, rows, empty = _read_csv(path)
            source = detect_binance_source(headers)
            if source == "unknown":
                self._unknown_files += 1
                if rows:
                    self.fuentes_materiales_no_soportadas.append("archivo Binance no reconocido")
                continue

            recognized += 1
            sec = self._sections[source]
            if not sec.detectado:
                sec.detectado = True
                sec.vacio = empty
            else:
                # Varias exportaciones de la misma fuente: solo es "vacía" si
                # TODAS lo son.
                sec.vacio = sec.vacio and empty
            sec.registros += len(rows)
            tz = _tz_from_filename(filename)
            if tz:
                self._tz_offsets.add(tz)

            for row in rows:
                digest = _row_digest(source, row)
                previous_file = self._cross_file_rows.get(digest)
                if previous_file is not None and previous_file != path:
                    # Dos registros iguales pueden ser operaciones legítimas
                    # distintas: Spot exporta order ID, no trade ID único.
                    # Sin identidad inequívoca, omitir uno podría falsear FIFO.
                    # Mantener ambos y bloquear el PDF hasta conciliarlos.
                    if "filas_identicas_entre_exportaciones_sin_id_unico" not in self.fuentes_materiales_no_soportadas:
                        self.fuentes_materiales_no_soportadas.append(
                            "filas_identicas_entre_exportaciones_sin_id_unico"
                        )
                    self.advertencias.append(
                        f"Binance: filas indistinguibles de {source} en "
                        "exportaciones diferentes; posible duplicidad "
                        "o dos operaciones reales. Requiere conciliación."
                    )
                self._cross_file_rows[digest] = path
                self._source_rows[source].append((row, filename))

        if not recognized:
            raise BinanceMultiUserError(
                "wrong_files",
                "Ninguno de los archivos se reconoce como una exportación compatible de Binance.",
            )

        if len(self._tz_offsets) > 1:
            raise BinanceMultiUserError(
                "mixed_timezones",
                "Los archivos de Binance fueron exportados con zonas horarias distintas. "
                "Vuelve a descargarlos usando la misma zona horaria.",
            )

        self._process_spot()
        self._reconcile_spot_orders()
        self._process_convert()
        self._process_fiat_trades()
        self._process_crypto_transfers()
        self._process_fiat_cash()
        self._process_optional_sources()
        self._process_transaction_history()

        if self._unknown_files:
            self.advertencias.append(
                f"Binance: {self._unknown_files} archivo(s) no se reconocieron."
            )
        return self

    def _native_status_ok(self, raw: str, source: str) -> bool:
        """No omitir eventos financieros con estados nuevos o pendientes."""
        state = str(raw or "").strip().lower()
        if state in _SUCCESS:
            return True
        if state in {"failed", "failure", "rejected", "cancelled", "canceled", "expired"}:
            return False
        marker = f"estado_no_reconocido_{source}"
        if marker not in self.fuentes_materiales_no_soportadas:
            self.fuentes_materiales_no_soportadas.append(marker)
        return False

    def _process_spot(self) -> None:
        rows = self._source_rows["spot_trades"]
        if self._sections["spot_orders"].detectado:
            self.advertencias.append(
                "Binance: Historial de órdenes Spot usado solo para reconciliación; "
                "el FIFO usa Historial de operaciones Spot (fills)."
            )
        for row, _filename in rows:
            # Las columnas AOR incorporadas a los exports 2026 identifican
            # posibles rutas de conversión. Sin documentar qué activo y
            # cantidades terminan en cada tramo no deben tratarse como un
            # simple BUY/SELL del par original.
            aor_pair = row.get("par de conversión de aor", "").strip()
            aor_rate = row.get("tasa de conversión de aor", "").strip()
            if aor_pair or aor_rate:
                if "spot_aor_conversion_no_reconstruida" not in self.fuentes_materiales_no_soportadas:
                    self.fuentes_materiales_no_soportadas.append(
                        "spot_aor_conversion_no_reconstruida"
                    )
                continue
            side = row.get("lado", "").strip().upper()
            if side not in {"BUY", "SELL"}:
                self.fuentes_materiales_no_soportadas.append("lado Spot desconocido")
                continue
            fecha = _fecha(row.get("tiempo"))
            base_qty, base = _amount_asset(row.get("ejecutado"), field="Ejecutado")
            quote_qty, quote = _amount_asset(row.get("cantidad"), field="Cantidad")
            fee_qty, fee_asset = _amount_asset(row.get("tarifa"), field="Tarifa")
            if base_qty <= 0 or quote_qty <= 0 or fee_qty < 0:
                raise BinanceMultiUserError(
                    "invalid_spot_amount",
                    "Binance contiene cantidades Spot inválidas.",
                    category="parser_error",
                )
            pair = row.get("par", "").strip().upper()
            if pair != f"{base}{quote}":
                self.fuentes_materiales_no_soportadas.append("par_spot_inconsistente")
                self.advertencias.append(
                    "Binance Spot: el par no coincide con los activos explícitos "
                    "de Ejecutado/Cantidad. Se bloquea el informe."
                )
                continue

            if side == "BUY":
                self._register_exchange(
                    fecha=fecha, give_asset=quote, give_amount=quote_qty,
                    recv_asset=base, recv_amount=base_qty,
                    fee_asset=fee_asset, fee_amount=fee_qty,
                    source="Spot BUY", filename=_filename,
                )
            else:
                self._register_exchange(
                    fecha=fecha, give_asset=base, give_amount=base_qty,
                    recv_asset=quote, recv_amount=quote_qty,
                    fee_asset=fee_asset, fee_amount=fee_qty,
                    source="Spot SELL", filename=_filename,
                )

    def _reconcile_spot_orders(self) -> None:
        """Contrasta órdenes con ejecución contra todos sus fills Spot.

        Una orden Filled/Partially Filled sin trades, o con volúmenes distintos,
        puede indicar una exportación incompleta. No se infieren trades ni se
        descartan órdenes ejecutadas: la aceptación fiscal debe bloquear el PDF.
        """
        orders = self._source_rows["spot_orders"]
        if not orders:
            # El fichero de órdenes puede estar vacío porque corresponde a
            # un intervalo diferente del historial de operaciones. Con ambos
            # informes aportados no debe darse por completa la conciliación.
            if (self._sections["spot_orders"].detectado
                    and self._source_rows["spot_trades"]):
                self.fuentes_materiales_no_soportadas.append(
                    "spot_orders_ejecutadas_sin_fills_completos"
                )
            return

        fills: Dict[tuple, List[Decimal]] = {}
        for row, _filename in self._source_rows["spot_trades"]:
            order_id = row.get("número de pedido", "").strip()
            pair = row.get("par", "").strip().upper()
            side = row.get("lado", "").strip().upper()
            base_qty, base = _amount_asset(row.get("ejecutado"), field="Ejecutado")
            quote_qty, quote = _amount_asset(row.get("cantidad"), field="Cantidad")
            if not order_id or not pair or side not in {"BUY", "SELL"} or pair != base + quote:
                self.fuentes_materiales_no_soportadas.append(
                    "spot_fill_sin_identidad_reconciliable"
                )
                return
            totals = fills.setdefault((order_id, pair, side), [Decimal("0"), Decimal("0")])
            totals[0] += base_qty
            totals[1] += quote_qty

        executed_states = {"filled", "partially filled", "partially_filled", "partiallyfilled"}
        unfilled_states = {"new", "canceled", "cancelled", "expired", "rejected"}
        seen_order_keys: set[tuple] = set()
        missing_or_mismatched = False

        for row, _filename in orders:
            status = row.get("estado", "").strip().lower()
            raw_executed = row.get("ejecutado", "").strip()
            if not raw_executed or raw_executed in {"0", "0.0", "0.00"}:
                if status not in unfilled_states:
                    missing_or_mismatched = True
                continue

            try:
                base_qty, base_asset = _amount_asset(raw_executed, field="Ejecutado")
            except BinanceMultiUserError:
                missing_or_mismatched = True
                continue
            if base_qty < 0 or (base_qty == 0 and status in executed_states):
                missing_or_mismatched = True
                continue
            if base_qty == 0:
                continue

            try:
                quote_qty, quote_asset = _amount_asset(
                    row.get("total de trading"), field="Total de trading"
                )
            except BinanceMultiUserError:
                missing_or_mismatched = True
                continue
            if quote_qty <= 0:
                missing_or_mismatched = True
                continue

            order_id = row.get("número de pedido", "").strip()
            pair = row.get("par", "").strip().upper()
            side = row.get("lado", "").strip().upper()
            key = (order_id, pair, side)
            if (
                not order_id or side not in {"BUY", "SELL"}
                or pair != base_asset + quote_asset
                or key in seen_order_keys
            ):
                missing_or_mismatched = True
                continue
            seen_order_keys.add(key)
            native = fills.get(key)
            if native is None or native[0] != base_qty or native[1] != quote_qty:
                missing_or_mismatched = True

        # También exigir que cada orden con fills aparezca en el fichero
        # de órdenes; comprobar solo en la otra dirección puede aceptar
        # una exportación parcial y un FIFO con cobertura no demostrada.
        if set(fills) - seen_order_keys:
            missing_or_mismatched = True

        if missing_or_mismatched:
            self.fuentes_materiales_no_soportadas.append(
                "spot_orders_ejecutadas_sin_fills_completos"
            )

    def _process_convert(self) -> None:
        for row, _filename in self._source_rows["convert_orders"]:
            if not self._native_status_ok(row.get("estado"), "convert_orders"):
                continue
            fecha = _fecha(row.get("tiempo"))
            give_qty, give_asset = _amount_asset(row.get("vender"), field="Vender")
            recv_qty, recv_asset = _amount_asset(row.get("comprar"), field="Comprar")
            if give_qty <= 0 or recv_qty <= 0:
                raise BinanceMultiUserError(
                    "invalid_convert_amount",
                    "Binance contiene cantidades Convert inválidas.",
                    category="parser_error",
                )
            self._register_exchange(
                fecha=fecha, give_asset=give_asset, give_amount=give_qty,
                recv_asset=recv_asset, recv_amount=recv_qty,
                fee_asset=None, fee_amount=Decimal("0"),
                source="Convert", filename=_filename,
            )

    def _process_fiat_trades(self) -> None:
        for row, _filename in self._source_rows["fiat_trade"]:
            if not self._native_status_ok(row.get("estado"), "fiat_trade"):
                continue
            fecha = _fecha(row.get("tiempo"))
            give_qty, give_asset = _amount_asset(
                row.get("cantidad a gastar"), field="Cantidad a gastar"
            )
            recv_qty, recv_asset = _amount_asset(
                row.get("recibir cantidad"), field="Recibir cantidad"
            )
            fee_qty, fee_asset = _amount_asset(row.get("tarifa"), field="Tarifa")
            if give_qty <= 0 or recv_qty <= 0 or fee_qty < 0:
                raise BinanceMultiUserError(
                    "invalid_fiat_trade",
                    "Binance contiene una compra/venta fiat con cantidades inválidas.",
                    category="parser_error",
                )
            self._register_exchange(
                fecha=fecha, give_asset=give_asset, give_amount=give_qty,
                recv_asset=recv_asset, recv_amount=recv_qty,
                fee_asset=fee_asset, fee_amount=fee_qty,
                source="Fiat trade", filename=_filename,
                payment_method=row.get("método", "").strip(),
            )

    def _register_exchange(
        self, *, fecha: str, give_asset: str, give_amount: Decimal,
        recv_asset: str, recv_amount: Decimal,
        fee_asset: Optional[str], fee_amount: Decimal, source: str,
        filename: str, payment_method: str = "",
    ) -> None:
        give_asset = give_asset.upper()
        recv_asset = recv_asset.upper()
        fee_asset = fee_asset.upper() if fee_asset else None

        if source.startswith("Spot "):
            source_group = "spot"
        elif source == "Convert":
            source_group = "convert"
        elif source == "Fiat trade":
            source_group = "fiat"
        else:
            source_group = "other"
        native_key = (source_group, fecha, give_asset, recv_asset)
        totals = self._native_exchange_totals.setdefault(
            native_key, [Decimal("0"), Decimal("0")]
        )
        totals[0] += give_amount
        totals[1] += recv_amount
        if fee_asset and fee_amount > 0:
            fees = self._native_exchange_fee_totals.setdefault(native_key, {})
            fees[fee_asset] = fees.get(fee_asset, Decimal("0")) + fee_amount

        recv_net = recv_amount
        if fee_asset == recv_asset and fee_amount > 0:
            recv_net = recv_amount - fee_amount
            if recv_net <= 0:
                raise BinanceMultiUserError(
                    "fee_exceeds_received",
                    "Binance contiene una comisión superior al activo recibido.",
                    category="parser_error",
                )

        self.intercambios_nativos.append(BinanceNativeExchange(
            source=source, filename=filename, local_time=fecha,
            given_asset=give_asset, given_amount=give_amount,
            received_asset=recv_asset, received_amount=recv_amount,
            fee_asset=fee_asset, fee_amount=fee_amount,
            payment_method=payment_method,
        ))

        if give_asset == "EUR" and recv_asset != "EUR":
            eur_cost = give_amount + (fee_amount if fee_asset == "EUR" else Decimal("0"))
            self.compraventas.append(OperacionCompraventa(
                fecha=fecha, tipo="COMPRA", activo=recv_asset,
                cantidad=float(recv_net), contraparte="EUR", importe=float(eur_cost),
                fee_activo=fee_asset or recv_asset, fee_cantidad=float(fee_amount),
            ))
            if fee_amount > 0 and fee_asset not in {"EUR", recv_asset}:
                self._pending_fee(fecha, source, fee_asset, fee_amount)
            return

        if recv_asset == "EUR" and give_asset != "EUR":
            self.compraventas.append(OperacionCompraventa(
                fecha=fecha, tipo="VENTA", activo=give_asset,
                cantidad=float(give_amount), contraparte="EUR", importe=float(recv_amount),
                fee_activo=fee_asset or "EUR", fee_cantidad=float(fee_amount),
            ))
            if fee_amount > 0 and fee_asset != "EUR":
                self._pending_fee(fecha, source, fee_asset, fee_amount)
            return

        if fee_asset == give_asset and fee_amount > 0:
            self._pending_fee(fecha, source, fee_asset, fee_amount)
        elif fee_amount > 0 and fee_asset not in {recv_asset}:
            self._pending_fee(fecha, source, fee_asset, fee_amount)

        self.swaps.append(OperacionSwap(
            fecha=fecha,
            activo_entregado=give_asset, cantidad_entregada=float(give_amount),
            activo_recibido=recv_asset, cantidad_recibida=float(recv_net),
            nota=source,
        ))
        self.valoraciones_pendientes.append({
            "fecha": fecha, "fuente": source, "motivo": "permuta_sin_valor_eur",
            "entregado": give_asset, "recibido": recv_asset,
        })

    def _pending_fee(self, fecha: str, source: str, asset: str, amount: Decimal) -> None:
        self.comisiones_pendientes.append({
            "fecha": fecha, "fuente": source, "activo": asset, "cantidad": str(amount),
        })

    def _process_crypto_transfers(self) -> None:
        for source, subtype, sign in (
            ("crypto_deposit", "Depósito cripto", 1),
            ("crypto_withdrawal", "Retiro cripto", -1),
        ):
            for row, _filename in self._source_rows[source]:
                if not self._native_status_ok(row.get("estado"), source):
                    continue
                fecha = _fecha(row.get("tiempo"))
                amount = _decimal(row.get("cantidad"), field="Cantidad")
                if amount <= 0:
                    raise BinanceMultiUserError(
                        "invalid_transfer_amount",
                        "Binance contiene una transferencia con cantidad inválida.",
                        category="parser_error",
                    )
                asset = row.get("moneda", "").strip().upper()
                if not re.fullmatch(r"[A-Z0-9]{2,20}", asset):
                    raise BinanceMultiUserError(
                        "invalid_transfer_asset",
                        "Binance contiene una transferencia sin identificador de activo válido.",
                        category="parser_error",
                    )
                key = (source, fecha, asset, amount)
                self._native_transfer_keys[key] = (
                    self._native_transfer_keys.get(key, 0) + 1
                )
                self.movimientos.append(OperacionMovimiento(
                    fecha=fecha, subtipo=subtype, activo=asset,
                    cantidad=float(amount) * sign,
                    observacion=f"Red: {row.get('red', '').strip()}",
                ))
                if source == "crypto_withdrawal":
                    fee = _decimal(row.get("tarifa"), field="Tarifa")
                    if fee < 0:
                        raise BinanceMultiUserError(
                            "invalid_withdrawal_fee",
                            "Binance contiene una comisión de retiro inválida.",
                            category="parser_error",
                        )
                    if fee > 0:
                        self._pending_fee(fecha, "Retiro cripto", asset, fee)

    def _process_fiat_cash(self) -> None:
        for source, subtype in (
            ("fiat_deposit", "Depósito fiat"),
            ("fiat_withdrawal", "Retiro fiat"),
        ):
            for row, _filename in self._source_rows[source]:
                if not self._native_status_ok(row.get("estado"), source):
                    continue
                field = "importe de depósito" if source == "fiat_deposit" else "importe de retiro"
                gross, asset = _amount_asset(row.get(field), field=field)
                received, received_asset = _amount_asset(
                    row.get("recibir cantidad"), field="Recibir cantidad"
                )
                fee, fee_asset = _amount_asset(row.get("tarifa"), field="Tarifa")
                # Datos reales Binance: el importe solicitado es bruto; el
                # recibido es neto después de la comisión de procesamiento.
                # Un depósito acredita el neto en Binance. Una retirada
                # consume el bruto de Binance y acredita el neto al banco.
                # No inferir movimientos netos omitiendo la tarifa.
                if gross <= 0 or received <= 0:
                    raise BinanceMultiUserError(
                        "invalid_fiat_cash_amount",
                        "Binance contiene un movimiento fiat ejecutado con "
                        "cantidad no positiva.",
                        category="parser_error",
                    )
                if (
                    fee < 0 or asset != received_asset or asset != fee_asset
                    or gross - received != fee
                ):
                    raise BinanceMultiUserError(
                        "fiat_cash_fee_mismatch",
                        "Binance contiene un depósito o retiro fiat con importes "
                        "bruto, neto y comisión que no concilian. No se puede "
                        "reconstruir el movimiento sin inventar cantidades.",
                        category="parser_error",
                    )
                account_delta = received if source == "fiat_deposit" else -gross
                fecha = _fecha(row.get("tiempo"))
                key = (source, fecha, asset, abs(account_delta))
                self._native_cash_keys[key] = self._native_cash_keys.get(key, 0) + 1
                method = row.get("método", "")
                fee_note = f" | Comisión fiat: {fee} {asset}" if fee > 0 else ""
                self.movimientos.append(OperacionMovimiento(
                    fecha=fecha, subtipo=subtype,
                    activo=asset, cantidad=float(account_delta),
                    observacion=f"{method}{fee_note}",
                ))

    def _process_optional_sources(self) -> None:
        for source in ("recurring_convert", "fiat_exchange"):
            if self._source_rows[source]:
                self.fuentes_materiales_no_soportadas.append(source)

    @staticmethod
    def _tx_group_legs(group: List[dict], negative_ops: set[str], positive_ops: set[str]):
        """Devuelve una única pata negativa y positiva agregadas, o None.

        La deduplicación solo se permite cuando cada lado usa exactamente un
        activo y los signos son coherentes.
        """
        neg: Dict[str, Decimal] = {}
        pos: Dict[str, Decimal] = {}
        for row in group:
            op = row.get("operación", "").strip()
            if op not in negative_ops | positive_ops:
                continue
            asset = row.get("moneda", "").strip().upper()
            amount = _decimal(row.get("cambio"), field="Cambio")
            if op in negative_ops:
                if amount >= 0:
                    return None
                neg[asset] = neg.get(asset, Decimal("0")) + (-amount)
            elif op in positive_ops:
                if amount <= 0:
                    return None
                pos[asset] = pos.get(asset, Decimal("0")) + amount
        if len(neg) != 1 or len(pos) != 1:
            return None
        give_asset, give_amount = next(iter(neg.items()))
        recv_asset, recv_amount = next(iter(pos.items()))
        return give_asset, give_amount, recv_asset, recv_amount

    def _matching_native_exchange(
        self, *, fecha: str, give_asset: str, give_amount: Decimal,
        recv_asset: str, recv_amount: Decimal, groups: Optional[set[str]] = None,
        tolerance_seconds: int = 0,
    ) -> Optional[tuple]:
        """Busca una única identidad nativa exacta para reconciliación.

        No hay fuzzy matching de cantidades. Para Convert se admite únicamente
        la tolerancia temporal ya existente en el parser legacy (≤2s).
        """
        target_dt = datetime.strptime(fecha, "%Y-%m-%d %H:%M:%S")
        candidates = []
        for key, totals in self._native_exchange_totals.items():
            group, native_fecha, native_give, native_recv = key
            if groups is not None and group not in groups:
                continue
            if native_give != give_asset or native_recv != recv_asset:
                continue
            try:
                native_dt = datetime.strptime(native_fecha, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                continue
            if abs((native_dt - target_dt).total_seconds()) > tolerance_seconds:
                continue
            if totals[0] == give_amount and totals[1] == recv_amount:
                candidates.append(key)
        if len(candidates) == 1:
            return candidates[0]
        if len(candidates) > 1:
            marker = "solape_ambiguo_fuentes_nativas"
            if marker not in self.fuentes_materiales_no_soportadas:
                self.fuentes_materiales_no_soportadas.append(marker)
        return None

    def _require_matched_native_tx_fees(self, key: tuple, group_rows: List[dict]) -> None:
        """No descartar fees del ledger sin comprobarlas contra la fuente nativa.

        El matching de patas por sí solo no acredita que una comisión de otro
        activo esté ya representada en Spot/fiat/Convert.
        """
        tx_fees: Dict[str, Decimal] = {}
        for row in group_rows:
            if row.get("operación", "").strip() != "Transaction Fee":
                continue
            asset = row.get("moneda", "").strip().upper()
            amount = _decimal(row.get("cambio"), field="Cambio")
            if not asset or amount > 0:
                raise BinanceMultiUserError(
                    "native_tx_fee_mismatch",
                    "Binance contiene una comisión de Transaction History sin signo "
                    "o activo conciliable con la fuente nativa.",
                    category="parser_error",
                )
            if amount < 0:
                tx_fees[asset] = tx_fees.get(asset, Decimal("0")) - amount
        if tx_fees and tx_fees != self._native_exchange_fee_totals.get(key, {}):
            raise BinanceMultiUserError(
                "native_tx_fee_mismatch",
                "Las comisiones de Transaction History no coinciden con las de "
                "la operación nativa. No se puede descartar ese movimiento.",
                category="parser_error",
            )

    def _filter_exact_tx_duplicates(self, rows: List[dict]) -> List[dict]:
        """Elimina solo duplicados demostrados frente a fuentes nativas.

        Lo no demostrado se conserva para ClasificadorBinanceTx. Así Spot no
        puede borrar por accidente Binance Pay, Convert legacy o ventas que no
        aparezcan en el fichero nativo.
        """
        drop: set[int] = set()

        # Transaction Sold/Revenue y Buy/Spend se agrupan por segundo + cuenta,
        # igual que el fallback seguro, pero sólo se omiten si las patas exactas
        # existen en una fuente nativa.
        exact_groups: Dict[tuple, List[int]] = {}
        exact_ops = {
            "Transaction Sold", "Transaction Revenue",
            "Transaction Buy", "Transaction Spend", "Transaction Fee",
        }
        for idx, row in enumerate(rows):
            if row.get("operación", "").strip() not in exact_ops:
                continue
            key = (_fecha(row.get("tiempo")), row.get("cuenta", "").strip())
            exact_groups.setdefault(key, []).append(idx)

        for (fecha, _cuenta), indices in exact_groups.items():
            group_rows = [rows[i] for i in indices]
            ops = {r.get("operación", "").strip() for r in group_rows}
            # Venta
            if {"Transaction Sold", "Transaction Revenue"} <= ops and not (
                {"Transaction Buy", "Transaction Spend"} & ops
            ):
                legs = self._tx_group_legs(
                    group_rows, {"Transaction Sold"}, {"Transaction Revenue"}
                )
                native_key = (self._matching_native_exchange(
                    fecha=fecha, give_asset=legs[0], give_amount=legs[1],
                    recv_asset=legs[2], recv_amount=legs[3],
                    groups={"spot", "fiat", "convert"},
                ) if legs else None)
                if native_key:
                    self._require_matched_native_tx_fees(native_key, group_rows)
                    drop.update(indices)
                    continue

            # Compra / Binance Pay
            if {"Transaction Buy", "Transaction Spend"} <= ops and not (
                {"Transaction Sold", "Transaction Revenue"} & ops
            ):
                legs = self._tx_group_legs(
                    group_rows, {"Transaction Spend"}, {"Transaction Buy"}
                )
                native_key = (self._matching_native_exchange(
                    fecha=fecha, give_asset=legs[0], give_amount=legs[1],
                    recv_asset=legs[2], recv_amount=legs[3],
                    groups={"spot", "fiat", "convert"},
                ) if legs else None)
                if native_key:
                    self._require_matched_native_tx_fees(native_key, group_rows)
                    drop.update(indices)

        # Binance Convert: reproducir la ventana temporal del legacy y comparar
        # exclusivamente contra Convert nativo.
        convert_indices = [
            i for i, r in enumerate(rows)
            if r.get("operación", "").strip() == "Binance Convert"
        ]
        convert_indices.sort(key=lambda i: _fecha(rows[i].get("tiempo")))
        clusters: List[List[int]] = []
        current: List[int] = []
        previous_dt = None
        for idx in convert_indices:
            dt = datetime.strptime(_fecha(rows[idx].get("tiempo")), "%Y-%m-%d %H:%M:%S")
            if previous_dt is not None and (dt - previous_dt).total_seconds() > 2:
                clusters.append(current)
                current = []
            current.append(idx)
            previous_dt = dt
        if current:
            clusters.append(current)

        for indices in clusters:
            group_rows = [rows[i] for i in indices]
            fecha = _fecha(group_rows[0].get("tiempo"))
            legs = self._tx_group_legs(
                group_rows, {"Binance Convert"}, {"Binance Convert"}
            )
            # _tx_group_legs no puede distinguir signo usando el mismo op;
            # Convert se agrega explícitamente por signo.
            neg: Dict[str, Decimal] = {}
            pos: Dict[str, Decimal] = {}
            for row in group_rows:
                asset = row.get("moneda", "").strip().upper()
                amount = _decimal(row.get("cambio"), field="Cambio")
                if amount < 0:
                    neg[asset] = neg.get(asset, Decimal("0")) + (-amount)
                elif amount > 0:
                    pos[asset] = pos.get(asset, Decimal("0")) + amount
            if len(neg) == 1 and len(pos) == 1:
                give_asset, give_amount = next(iter(neg.items()))
                recv_asset, recv_amount = next(iter(pos.items()))
                if self._matching_native_exchange(
                    fecha=fecha, give_asset=give_asset, give_amount=give_amount,
                    recv_asset=recv_asset, recv_amount=recv_amount,
                    groups={"convert"}, tolerance_seconds=2,
                ):
                    drop.update(indices)

        # Buy/Sell Crypto With Fiat con Wallet ID: sólo se omite si el grupo
        # contiene ambas patas y reproduce un trade fiat nativo.
        wallet_re = re.compile(r"Wallet/(\w+)", re.I)
        wallet_groups: Dict[tuple, List[int]] = {}
        for idx, row in enumerate(rows):
            op = row.get("operación", "").strip()
            if op not in {"Buy Crypto With Fiat", "Sell Crypto To Fiat"}:
                continue
            m = wallet_re.search(row.get("observación", "") or "")
            if not m:
                continue
            wallet_groups.setdefault((op, m.group(1)), []).append(idx)

        for (_op, _wallet), indices in wallet_groups.items():
            group_rows = [rows[i] for i in indices]
            neg: Dict[str, Decimal] = {}
            pos: Dict[str, Decimal] = {}
            for row in group_rows:
                asset = row.get("moneda", "").strip().upper()
                amount = _decimal(row.get("cambio"), field="Cambio")
                if amount < 0:
                    neg[asset] = neg.get(asset, Decimal("0")) + (-amount)
                elif amount > 0:
                    pos[asset] = pos.get(asset, Decimal("0")) + amount
            if len(neg) == 1 and len(pos) == 1:
                give_asset, give_amount = next(iter(neg.items()))
                recv_asset, recv_amount = next(iter(pos.items()))
                fecha = _fecha(group_rows[0].get("tiempo"))
                if self._matching_native_exchange(
                    fecha=fecha, give_asset=give_asset, give_amount=give_amount,
                    recv_asset=recv_asset, recv_amount=recv_amount,
                    groups={"fiat"},
                ):
                    drop.update(indices)

        # Transferencias: conciliación uno-a-uno por fecha + activo + cantidad.
        # Usar un set descartaría dos filas TX frente a una sola transferencia
        # nativa. Preservar la fila sobrante y bloquear la aceptación.
        remaining_crypto = dict(self._native_transfer_keys)
        remaining_fiat = dict(self._native_cash_keys)
        transfer_map = {
            "Deposit": ("crypto_deposit", 1),
            "Withdraw": ("crypto_withdrawal", -1),
            "Fiat Deposit": ("fiat_deposit", 1),
            "Fiat Withdraw": ("fiat_withdrawal", -1),
        }
        for idx, row in enumerate(rows):
            op = row.get("operación", "").strip()
            if op not in transfer_map:
                continue
            source, sign = transfer_map[op]
            fecha = _fecha(row.get("tiempo"))
            asset = row.get("moneda", "").strip().upper()
            amount = _decimal(row.get("cambio"), field="Cambio")
            expected = amount if sign > 0 else -amount
            if expected <= 0:
                continue
            key = (source, fecha, asset, expected)
            remaining = remaining_crypto if source.startswith("crypto_") else remaining_fiat
            if remaining.get(key, 0) > 0:
                remaining[key] -= 1
                drop.add(idx)
            elif key in remaining:
                marker = "transferencias_duplicadas_sin_identidad_univoca"
                if marker not in self.fuentes_materiales_no_soportadas:
                    self.fuentes_materiales_no_soportadas.append(marker)

        # Si existe una fuente fiat nativa y una operación fiat legacy sin Wallet
        # no puede ligarse inequívocamente, no la ocultamos: el parser legacy la
        # procesará o bloqueará. Nunca se deduplica por mera proximidad temporal.
        return [row for idx, row in enumerate(rows) if idx not in drop]

    def _merge_legacy_transaction_rows(self, rows: List[dict]) -> None:
        if not rows:
            return
        from clasificador_binance_tx import ClasificadorBinanceTx

        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", newline="", suffix=".csv", delete=False
            ) as tmp:
                tmp_path = tmp.name
                writer = csv.writer(tmp)
                writer.writerow([
                    "ID de usuario", "Tiempo", "Cuenta", "Operación",
                    "Moneda", "Cambio", "Observación",
                ])
                for row in rows:
                    writer.writerow([
                        "",
                        row.get("tiempo", ""),
                        row.get("cuenta", ""),
                        row.get("operación", ""),
                        row.get("moneda", ""),
                        row.get("cambio", ""),
                        row.get("observación", ""),
                    ])

            legacy = ClasificadorBinanceTx(tmp_path).clasificar()
            self.compraventas.extend(legacy.compraventas)
            self.swaps.extend(legacy.swaps)
            self.rendimientos.extend(legacy.rendimientos)
            self.movimientos.extend(legacy.movimientos)
            self.desconocidas.extend(legacy.desconocidas)
            self.advertencias.extend(legacy.advertencias)

            for income in legacy.rendimientos:
                self.valoraciones_pendientes.append({
                    "fecha": income.fecha,
                    "fuente": "Transaction History",
                    "motivo": "rendimiento_sin_valor_eur",
                    "activo": income.activo,
                })
            fee_rows = legacy.df.loc[
                legacy.df["Operación"] == "Transaction Fee",
                ["Tiempo", "Moneda", "Cambio"],
            ]
            for _, fee_row in fee_rows.iterrows():
                amount = abs(Decimal(str(fee_row["Cambio"])))
                if amount > 0:
                    self._pending_fee(
                        str(fee_row["Tiempo"]),
                        "Transaction History",
                        str(fee_row["Moneda"]),
                        amount,
                    )
        finally:
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

    def _process_transaction_history(self) -> None:
        rows = [row for row, _filename in self._source_rows["transaction_history"]]
        if not rows:
            return
        filtered = self._filter_exact_tx_duplicates(rows)
        omitted = len(rows) - len(filtered)
        if omitted:
            self.advertencias.append(
                f"Binance: {omitted} fila(s) de Transaction History se omitieron "
                "porque estaban reproducidas exactamente por una fuente nativa."
            )
        self._merge_legacy_transaction_rows(filtered)
