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
import re
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
        rows: List[dict] = []
        sentinel = False
        for raw in reader:
            if not any((c or "").strip() for c in raw):
                continue
            first = (raw[0] or "").strip().lower()
            if _NO_DATA in first:
                sentinel = True
                continue
            row = {k: (raw[i].strip() if i < len(raw) else "")
                   for i, k in enumerate(keys)}
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
        self.fuentes_materiales_no_soportadas: List[str] = []
        self._sections: Dict[str, _Section] = {k: _Section() for k in self.SOURCE_KEYS}
        self._unknown_files = 0
        self._source_rows: Dict[str, List[Tuple[dict, str]]] = {k: [] for k in self.SOURCE_KEYS}
        self._cross_file_rows: Dict[str, str] = {}
        self._tz_offsets: set[str] = set()

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
            sec.detectado = True
            sec.vacio = sec.vacio or empty
            sec.registros += len(rows)
            tz = _tz_from_filename(filename)
            if tz:
                self._tz_offsets.add(tz)

            for row in rows:
                digest = _row_digest(source, row)
                previous_file = self._cross_file_rows.get(digest)
                if previous_file is not None and previous_file != filename:
                    self.advertencias.append(
                        f"Binance: se omitió una fila duplicada de {source} "
                        "presente en más de una exportación."
                    )
                    continue
                self._cross_file_rows[digest] = filename
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

    def _process_spot(self) -> None:
        rows = self._source_rows["spot_trades"]
        if self._sections["spot_orders"].detectado:
            self.advertencias.append(
                "Binance: Historial de órdenes Spot usado solo para reconciliación; "
                "el FIFO usa Historial de operaciones Spot (fills)."
            )
        for row, _filename in rows:
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
            if pair and pair != f"{base}{quote}":
                self.advertencias.append(
                    f"Binance Spot: el par {pair} no coincide con los activos de la ejecución; "
                    "se usan los activos explícitos de Ejecutado/Cantidad."
                )

            if side == "BUY":
                self._register_exchange(
                    fecha=fecha, give_asset=quote, give_amount=quote_qty,
                    recv_asset=base, recv_amount=base_qty,
                    fee_asset=fee_asset, fee_amount=fee_qty,
                    source="Spot BUY",
                )
            else:
                self._register_exchange(
                    fecha=fecha, give_asset=base, give_amount=base_qty,
                    recv_asset=quote, recv_amount=quote_qty,
                    fee_asset=fee_asset, fee_amount=fee_qty,
                    source="Spot SELL",
                )

    def _process_convert(self) -> None:
        for row, _filename in self._source_rows["convert_orders"]:
            if not _status_ok(row.get("estado")):
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
                source="Convert",
            )

    def _process_fiat_trades(self) -> None:
        for row, _filename in self._source_rows["fiat_trade"]:
            if not _status_ok(row.get("estado")):
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
                source="Fiat trade",
            )

    def _register_exchange(
        self, *, fecha: str, give_asset: str, give_amount: Decimal,
        recv_asset: str, recv_amount: Decimal,
        fee_asset: Optional[str], fee_amount: Decimal, source: str,
    ) -> None:
        give_asset = give_asset.upper()
        recv_asset = recv_asset.upper()
        fee_asset = fee_asset.upper() if fee_asset else None

        recv_net = recv_amount
        if fee_asset == recv_asset and fee_amount > 0:
            recv_net = recv_amount - fee_amount
            if recv_net <= 0:
                raise BinanceMultiUserError(
                    "fee_exceeds_received",
                    "Binance contiene una comisión superior al activo recibido.",
                    category="parser_error",
                )

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
                if not _status_ok(row.get("estado")):
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
                if not _status_ok(row.get("estado")):
                    continue
                field = "importe de depósito" if source == "fiat_deposit" else "importe de retiro"
                qty, asset = _amount_asset(row.get(field), field=field)
                self.movimientos.append(OperacionMovimiento(
                    fecha=_fecha(row.get("tiempo")), subtipo=subtype,
                    activo=asset, cantidad=float(qty) * (1 if source == "fiat_deposit" else -1),
                    observacion=row.get("método", ""),
                ))

    def _process_optional_sources(self) -> None:
        for source in ("recurring_convert", "fiat_exchange"):
            if self._source_rows[source]:
                self.fuentes_materiales_no_soportadas.append(source)

    def _process_transaction_history(self) -> None:
        rows = self._source_rows["transaction_history"]
        if not rows:
            return

        richer_trade_sources = any(
            self._sections[k].detectado and self._sections[k].registros > 0
            for k in ("spot_trades", "convert_orders", "fiat_trade")
        )
        richer_crypto_transfers = any(
            self._sections[k].detectado and self._sections[k].registros > 0
            for k in ("crypto_deposit", "crypto_withdrawal")
        )
        richer_fiat_cash = any(
            self._sections[k].detectado and self._sections[k].registros > 0
            for k in ("fiat_deposit", "fiat_withdrawal")
        )

        if not richer_trade_sources:
            tx_files = []
            for path, filename in zip(self.filepaths, self.filenames):
                headers, _r, _empty = _read_csv(path)
                if detect_binance_source(headers) == "transaction_history":
                    tx_files.append((path, filename))
            from clasificador_binance_tx import ClasificadorBinanceTx
            for path, _filename in tx_files:
                legacy = ClasificadorBinanceTx(path).clasificar()
                self.compraventas.extend(legacy.compraventas)
                self.swaps.extend(legacy.swaps)
                self.rendimientos.extend(legacy.rendimientos)
                self.movimientos.extend(legacy.movimientos)
                self.desconocidas.extend(legacy.desconocidas)
                self.advertencias.extend(legacy.advertencias)

                # El wrapper multi debe conservar los guards fiscales del
                # clasificador legacy: rendimientos sin EUR y Transaction Fee
                # no pueden quedar autorizados por cambiar de tipo de clase.
                for income in legacy.rendimientos:
                    self.valoraciones_pendientes.append({
                        "fecha": income.fecha,
                        "fuente": "Transaction History",
                        "motivo": "rendimiento_sin_valor_eur",
                        "activo": income.activo,
                    })
                try:
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
                except Exception:
                    # Si cambia la forma interna del legacy, fail-closed:
                    # la aceptación posterior verá la operación desconocida o
                    # el propio parser legacy habrá fallado antes.
                    pass
            return

        for row, _filename in rows:
            op = row.get("operación", "").strip()
            if op in _TRADELIKE_TX:
                continue
            if richer_crypto_transfers and op in _CRYPTO_TRANSFER_TX:
                continue
            if richer_fiat_cash and op in _FIAT_TRANSFER_TX:
                continue

            fecha = _fecha(row.get("tiempo"))
            asset = row.get("moneda", "").strip().upper()
            amount = _decimal(row.get("cambio"), field="Cambio")
            account = row.get("cuenta", "")
            category = REGLAS_TX.get(op)
            if category == "RENDIMIENTO":
                self.rendimientos.append(OperacionRendimiento(
                    fecha=fecha, subtipo=op, activo=asset,
                    cantidad=float(amount), cuenta=account,
                ))
                self.valoraciones_pendientes.append({
                    "fecha": fecha, "fuente": "Transaction History",
                    "motivo": "rendimiento_sin_valor_eur", "activo": asset,
                })
            elif category == "MOVIMIENTO":
                self.movimientos.append(OperacionMovimiento(
                    fecha=fecha, subtipo=op, activo=asset, cantidad=float(amount),
                    observacion=row.get("observación", ""),
                ))
            else:
                self.desconocidas.append(OperacionDesconocida(
                    fecha=fecha, subtipo=op or "Operación Binance no reconocida",
                    activo=asset or "?", cantidad=float(amount), cuenta=account,
                ))
