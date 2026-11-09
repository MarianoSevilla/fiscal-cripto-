"""Importador Binance multifuente.

Normaliza exportaciones especializadas de Binance antes de alimentar MotorFIFO.
Las fuentes especializadas tienen precedencia sobre el Historial de transacciones.

Diseño fiscal:
- Spot Trades es la fuente canónica de fills (no Spot Orders).
- Convert Orders es la fuente canónica de conversiones.
- Fiat Buy/Sell es la fuente canónica de compras/ventas directas con fiat.
- Depósitos/retiros cripto son transferencias, no compraventas por sí mismos.
- Historial de transacciones queda como fuente complementaria/legacy.
- Nunca se inventa una valoración EUR: cualquier operación material sin EUR
  acreditado genera un bloqueo y no puede emitirse un informe parcial.

No contiene datos reales ni identificadores de usuarios.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
import hashlib
import math
import re
from typing import Iterable

import pandas as pd

from clasificador import (
    OperacionCompraventa,
    OperacionMovimiento,
    OperacionRendimiento,
    OperacionDesconocida,
)
from clasificador_binance_tx import ClasificadorBinanceTx
from csv_schema import leer_csv_texto, normalizar_cabeceras


_AMOUNT_RE = re.compile(r"^\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+))\s*([A-Za-z][A-Za-z0-9._-]*)\s*$")
_TZ_RE = re.compile(r"\(UTC([+-]\d{1,2})(?::?(\d{2}))?\)", re.IGNORECASE)


class BinanceMultiUserError(ValueError):
    def __init__(self, code: str, message: str, *, category: str = "user_error"):
        super().__init__(message)
        self.code = code
        self.category = category


@dataclass(frozen=True)
class BinanceCanonicalEvent:
    event_id: str
    fuente: str
    fecha: str
    tipo: str
    activo_entregado: str = ""
    cantidad_entregada: Decimal = Decimal("0")
    activo_recibido: str = ""
    cantidad_recibida: Decimal = Decimal("0")
    fee_activo: str = ""
    fee_cantidad: Decimal = Decimal("0")
    valor_eur: Decimal | None = None
    valoracion: str = "NO_APLICA"  # EUR_DIRECTO | PENDIENTE | NO_APLICA
    referencia: str = ""
    cuenta: str = ""
    timezone_hint: str = ""


@dataclass(frozen=True)
class BinanceValuationGap:
    code: str
    fuente: str
    fecha: str
    detalle: str


def _text(value) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def _decimal(value, *, field: str) -> Decimal:
    text = _text(value).replace(",", "")
    try:
        out = Decimal(text)
    except (InvalidOperation, ValueError) as exc:
        raise BinanceMultiUserError(
            "numeric_invalid",
            f"Datos fiscales no seguros: Binance contiene un valor numérico inválido en {field}.",
            category="parser_error",
        ) from exc
    if not out.is_finite():
        raise BinanceMultiUserError(
            "numeric_nonfinite",
            f"Datos fiscales no seguros: Binance contiene un valor no finito en {field}.",
            category="parser_error",
        )
    return out


def _amount_asset(value, *, field: str) -> tuple[Decimal, str]:
    m = _AMOUNT_RE.match(_text(value))
    if not m:
        raise BinanceMultiUserError(
            "amount_asset_invalid",
            f"Datos fiscales no seguros: Binance contiene un importe sin moneda interpretable en {field}.",
            category="parser_error",
        )
    return _decimal(m.group(1), field=field), m.group(2).upper()


def _date(value) -> str:
    text = _text(value)
    if not text:
        raise BinanceMultiUserError(
            "date_missing",
            "Datos fiscales no seguros: Binance contiene una operación sin fecha.",
            category="parser_error",
        )
    try:
        ts = pd.to_datetime(text, format="mixed", dayfirst=False)
    except Exception as exc:
        raise BinanceMultiUserError(
            "date_invalid",
            "Datos fiscales no seguros: Binance contiene una fecha no interpretable.",
            category="parser_error",
        ) from exc
    return ts.strftime("%Y-%m-%d %H:%M:%S")


def _event_id(source: str, *parts) -> str:
    body = "\x1f".join([source] + [_text(p) for p in parts])
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _timezone_hint(filename: str) -> str:
    m = _TZ_RE.search(filename or "")
    if not m:
        return ""
    hour = int(m.group(1))
    minute = int(m.group(2) or "0")
    sign = "+" if hour >= 0 else "-"
    return f"UTC{sign}{abs(hour):02d}:{minute:02d}"


def _is_empty_export(df: pd.DataFrame | None) -> bool:
    if df is None or df.empty:
        return True
    first = _text(df.iloc[0, 0]).lower()
    return first.startswith("no hay datos") or first.startswith("no data")


def _normal_df(path: str) -> pd.DataFrame | None:
    df = leer_csv_texto(path, encoding="utf-8-sig")
    if df is not None:
        df.columns = normalizar_cabeceras(df.columns)
    return df


def _filename_kind(filename: str) -> str:
    n = (filename or "").lower()
    # Ambiguous Fiat buy/sell schemas need the export name to establish direction.
    if "compras-de-fiat" in n or "fiat-buy" in n:
        return "fiat_buy"
    if "ventas-de-fiat" in n or "fiat-sell" in n:
        return "fiat_sell"
    if "depósitos-de-fiat" in n or "depositos-de-fiat" in n:
        return "fiat_deposit"
    if "retiros-de-fiat" in n:
        return "fiat_withdraw"
    if "intercambios-de-fiat" in n:
        return "fiat_exchange"
    if "compras-recurrentes" in n:
        return "convert_recurring"
    if "órdenes-de-convert" in n or "ordenes-de-convert" in n:
        return "convert"
    if "operaciones-de-spot" in n:
        return "spot_trade"
    if "órdenes-de-spot" in n or "ordenes-de-spot" in n:
        return "spot_order"
    if "historial-de-transacciones" in n:
        return "transaction_history"
    if "depósitos-" in n or "depositos-" in n:
        return "crypto_deposit"
    if "retiros-" in n:
        return "crypto_withdraw"
    return ""


def _detect_source(df: pd.DataFrame | None, filename: str) -> str:
    by_name = _filename_kind(filename)
    if _is_empty_export(df):
        return by_name or "empty"
    cols = set(df.columns)
    if {"Número de pedido", "Tiempo", "Par", "Lado", "Precio", "Ejecutado", "Cantidad", "Tarifa"} <= cols:
        return "spot_trade"
    if {"Número de pedido", "Tiempo", "Par", "Lado", "Precio de la orden", "Cantidad de la orden"} <= cols:
        return "spot_order"
    if {"Tiempo", "Billetera", "Vender", "Comprar", "Precio", "Estado"} <= cols:
        return "convert"
    if {"ID de usuario", "Cuenta", "Operación"} <= cols and ({"Tiempo", "Hora"} & cols):
        return "transaction_history"
    if {"Tiempo", "Moneda", "Red", "Cantidad", "TXID", "Estado"} <= cols:
        return "crypto_withdraw" if "Tarifa" in cols else "crypto_deposit"
    if {"Tiempo", "Método", "Importe de depósito", "Recibir cantidad", "Estado"} <= cols:
        return "fiat_deposit"
    if {"Tiempo", "Método", "Importe de retiro", "Recibir cantidad", "Estado"} <= cols:
        return "fiat_withdraw"
    if {"Tiempo", "Método", "Cantidad a gastar", "Recibir cantidad", "Precio", "Estado"} <= cols:
        if by_name in {"fiat_buy", "fiat_sell"}:
            return by_name
        raise BinanceMultiUserError(
            "fiat_direction_ambiguous",
            "El CSV fiat de Binance no permite distinguir de forma segura una compra de una venta. "
            "Sube el archivo original sin renombrarlo.",
        )
    if by_name:
        return by_name
    raise BinanceMultiUserError(
        "unsupported_binance_source",
        "Uno de los archivos de Binance no corresponde a una fuente soportada por el importador multifuente.",
        category="parser_error",
    )


class ClasificadorBinanceMulti:
    """Clasificador multiarchivo con precedencia de fuentes y aceptación fail-closed."""

    MAX_FILES = 16

    def __init__(self, filepaths: list[str], filenames: list[str] | None = None):
        if not filepaths:
            raise BinanceMultiUserError("no_files", "No se recibió ningún archivo de Binance.")
        if len(filepaths) > self.MAX_FILES:
            raise BinanceMultiUserError(
                "too_many_files", f"Demasiados archivos de Binance. Máximo {self.MAX_FILES} por análisis."
            )
        self.filepaths = list(filepaths)
        self.filenames = list(filenames or [Path(p).name for p in filepaths])
        if len(self.filepaths) != len(self.filenames):
            raise BinanceMultiUserError("file_name_mismatch", "No se puede identificar de forma segura el conjunto de archivos Binance.")
        digests = []
        for path in self.filepaths:
            with open(path, "rb") as fh:
                digests.append(hashlib.sha256(fh.read()).hexdigest())
        if len(set(digests)) != len(digests):
            raise BinanceMultiUserError(
                "duplicate_file",
                "Has subido el mismo archivo de Binance más de una vez. Elimina el duplicado y vuelve a intentarlo.",
            )

        self.compraventas: list[OperacionCompraventa] = []
        self.swaps = []  # No se crean swaps sin valoración EUR acreditada.
        self.rendimientos: list[OperacionRendimiento] = []
        self.movimientos: list[OperacionMovimiento] = []
        self.desconocidas: list[OperacionDesconocida] = []
        self.advertencias: list[str] = []
        self.eventos: list[BinanceCanonicalEvent] = []
        self.bloqueos_valoracion: list[BinanceValuationGap] = []
        self.resumen_archivos: dict = {}
        self._seen_event_ids: set[str] = set()
        self._specialized_families: set[str] = set()

    def clasificar(self):
        parsed: list[tuple[str, str, str, pd.DataFrame | None]] = []
        for path, filename in zip(self.filepaths, self.filenames):
            df = _normal_df(path)
            source = _detect_source(df, filename)
            empty = _is_empty_export(df)
            summary = self.resumen_archivos.setdefault(source, {
                "detectado": False, "vacio": True, "registros": 0, "archivos": 0,
            })
            summary["detectado"] = True
            summary["archivos"] += 1
            summary["registros"] += 0 if empty else int(len(df))
            summary["vacio"] = summary["registros"] == 0
            parsed.append((source, path, filename, df))
            if not empty and source in {"spot_trade", "convert", "fiat_buy", "fiat_sell"}:
                self._specialized_families.add(source)

        # Specialized sources first; Transaction History only fills legacy/complementary gaps.
        priority = {
            "spot_trade": 10, "convert": 20, "fiat_buy": 30, "fiat_sell": 31,
            "crypto_deposit": 40, "crypto_withdraw": 41,
            "fiat_deposit": 50, "fiat_withdraw": 51,
            "spot_order": 80, "convert_recurring": 81, "fiat_exchange": 82,
            "transaction_history": 90, "empty": 99,
        }
        for source, path, filename, df in sorted(parsed, key=lambda x: priority.get(x[0], 95)):
            if _is_empty_export(df):
                continue
            handler = getattr(self, f"_parse_{source}", None)
            if handler is None:
                raise BinanceMultiUserError(
                    "unsupported_binance_source",
                    f"Fuente Binance todavía no soportada de forma segura: {source}.",
                    category="parser_error",
                )
            handler(df, filename)

        if not any(self.resumen_archivos.values()):
            raise BinanceMultiUserError("all_empty", "Los archivos de Binance no contienen operaciones.")
        return self

    def _add_event(self, event: BinanceCanonicalEvent):
        if event.event_id in self._seen_event_ids:
            return
        self._seen_event_ids.add(event.event_id)
        self.eventos.append(event)

    def _gap(self, code: str, source: str, fecha: str, detalle: str):
        self.bloqueos_valoracion.append(BinanceValuationGap(code, source, fecha, detalle))

    @staticmethod
    def _ok(row) -> bool:
        status = _text(row.get("Estado", "")).lower()
        return not status or status in {"successful", "success", "completed", "completado", "ok"}

    def _parse_spot_trade(self, df, filename):
        tz = _timezone_hint(filename)
        for idx, row in df.iterrows():
            fecha = _date(row["Tiempo"])
            executed_qty, executed_asset = _amount_asset(row["Ejecutado"], field="Ejecutado")
            quote_qty, quote_asset = _amount_asset(row["Cantidad"], field="Cantidad")
            fee_qty, fee_asset = _amount_asset(row["Tarifa"], field="Tarifa")
            side = _text(row["Lado"]).upper()
            order_id = _text(row["Número de pedido"])
            eid = _event_id("spot_trade", order_id, fecha, idx, executed_qty, executed_asset, quote_qty, quote_asset, fee_qty, fee_asset)
            if side == "BUY":
                delivered_asset, delivered_qty = quote_asset, quote_qty
                received_asset, received_qty = executed_asset, executed_qty
            elif side == "SELL":
                delivered_asset, delivered_qty = executed_asset, executed_qty
                received_asset, received_qty = quote_asset, quote_qty
            else:
                raise BinanceMultiUserError("spot_side_invalid", "Binance contiene una operación Spot con lado no reconocido.", category="parser_error")
            value_eur = delivered_qty if delivered_asset == "EUR" else received_qty if received_asset == "EUR" else None
            valuation = "EUR_DIRECTO" if value_eur is not None else "PENDIENTE"
            event = BinanceCanonicalEvent(
                eid, "spot_trade", fecha, f"SPOT_{side}",
                delivered_asset, delivered_qty, received_asset, received_qty,
                fee_asset, fee_qty, value_eur, valuation, order_id, "", tz,
            )
            self._add_event(event)
            if value_eur is None:
                self._gap("spot_non_eur", "spot_trade", fecha,
                          f"Fill Spot {delivered_asset}→{received_asset} sin valoración EUR acreditada.")
                continue
            if fee_qty and fee_asset not in {"", "EUR", delivered_asset, received_asset}:
                self._gap("spot_fee_third_asset", "spot_trade", fecha,
                          f"Comisión Spot pagada en {fee_asset} sin valoración EUR acreditada.")
                continue
            if side == "BUY":
                net_received = received_qty
                acquisition_cost = delivered_qty
                if fee_qty:
                    if fee_asset == received_asset:
                        net_received = received_qty - fee_qty
                        if net_received <= 0:
                            raise BinanceMultiUserError(
                                "spot_fee_invalid",
                                "Datos fiscales no seguros: la comisión Spot consume toda la cantidad comprada.",
                                category="parser_error",
                            )
                    elif fee_asset == "EUR":
                        acquisition_cost = delivered_qty + fee_qty
                    elif fee_asset:
                        # Already registered as a valuation gap above.
                        continue
                self.compraventas.append(OperacionCompraventa(
                    fecha, "COMPRA", received_asset, float(net_received), "EUR",
                    float(acquisition_cost), "", 0.0,
                ))
            else:
                if fee_qty and fee_asset == delivered_asset:
                    self._gap("spot_sell_fee_base_asset", "spot_trade", fecha,
                              f"Comisión de venta Spot pagada en {fee_asset}; requiere tratamiento fiscal separado.")
                    continue
                self.compraventas.append(OperacionCompraventa(
                    fecha, "VENTA", delivered_asset, float(delivered_qty), "EUR",
                    float(received_qty), fee_asset, float(fee_qty),
                ))

    def _parse_convert(self, df, filename):
        tz = _timezone_hint(filename)
        for idx, row in df.iterrows():
            if not self._ok(row):
                continue
            fecha = _date(row["Tiempo"])
            sell_qty, sell_asset = _amount_asset(row["Vender"], field="Vender")
            buy_qty, buy_asset = _amount_asset(row["Comprar"], field="Comprar")
            wallet = _text(row.get("Billetera", ""))
            ref = _text(row.get("Par", ""))
            eid = _event_id("convert", fecha, wallet, ref, sell_qty, sell_asset, buy_qty, buy_asset, idx)
            value_eur = sell_qty if sell_asset == "EUR" else buy_qty if buy_asset == "EUR" else None
            event = BinanceCanonicalEvent(
                eid, "convert", fecha, "CONVERT", sell_asset, sell_qty, buy_asset, buy_qty,
                "", Decimal("0"), value_eur,
                "EUR_DIRECTO" if value_eur is not None else "PENDIENTE", ref, wallet, tz,
            )
            self._add_event(event)
            if value_eur is None:
                self._gap("convert_non_eur", "convert", fecha,
                          f"Convert {sell_asset}→{buy_asset} sin valoración EUR acreditada.")
                continue
            if sell_asset == "EUR":
                self.compraventas.append(OperacionCompraventa(
                    fecha, "COMPRA", buy_asset, float(buy_qty), "EUR", float(sell_qty), buy_asset, 0.0
                ))
            elif buy_asset == "EUR":
                self.compraventas.append(OperacionCompraventa(
                    fecha, "VENTA", sell_asset, float(sell_qty), "EUR", float(buy_qty), "EUR", 0.0
                ))

    def _parse_fiat_buy(self, df, filename):
        self._parse_fiat_trade(df, filename, "BUY")

    def _parse_fiat_sell(self, df, filename):
        self._parse_fiat_trade(df, filename, "SELL")

    def _parse_fiat_trade(self, df, filename, side: str):
        tz = _timezone_hint(filename)
        for idx, row in df.iterrows():
            if not self._ok(row):
                continue
            fecha = _date(row["Tiempo"])
            spend_qty, spend_asset = _amount_asset(row["Cantidad a gastar"], field="Cantidad a gastar")
            recv_qty, recv_asset = _amount_asset(row["Recibir cantidad"], field="Recibir cantidad")
            fee_qty, fee_asset = _amount_asset(row.get("Tarifa", "0 EUR"), field="Tarifa")
            ref = _text(row.get("ID de transacción", idx))
            eid = _event_id(f"fiat_{side.lower()}", ref, fecha, spend_qty, spend_asset, recv_qty, recv_asset, fee_qty, fee_asset)
            event = BinanceCanonicalEvent(
                eid, f"fiat_{side.lower()}", fecha, f"FIAT_{side}",
                spend_asset, spend_qty, recv_asset, recv_qty, fee_asset, fee_qty,
                spend_qty if spend_asset == "EUR" else recv_qty if recv_asset == "EUR" else None,
                "EUR_DIRECTO" if "EUR" in {spend_asset, recv_asset} else "PENDIENTE",
                ref, "", tz,
            )
            self._add_event(event)
            if side == "BUY":
                if spend_asset != "EUR" or recv_asset == "EUR":
                    self._gap("fiat_buy_not_eur", "fiat_buy", fecha, "Compra fiat sin pata EUR verificable.")
                    continue
                # Binance's observed export reports the total amount spent and fee separately;
                # do not add fee again to the acquisition cost.
                self.compraventas.append(OperacionCompraventa(
                    fecha, "COMPRA", recv_asset, float(recv_qty), "EUR",
                    float(spend_qty), fee_asset, 0.0,
                ))
            else:
                if recv_asset != "EUR" or spend_asset == "EUR":
                    self._gap("fiat_sell_not_eur", "fiat_sell", fecha, "Venta fiat sin pata EUR verificable.")
                    continue
                if fee_qty and fee_asset != "EUR":
                    self._gap("fiat_sell_fee_non_eur", "fiat_sell", fecha,
                              f"Comisión de venta fiat en {fee_asset} sin valoración EUR acreditada.")
                    continue
                self.compraventas.append(OperacionCompraventa(
                    fecha, "VENTA", spend_asset, float(spend_qty), "EUR",
                    float(recv_qty), fee_asset or "EUR", float(fee_qty),
                ))

    def _parse_crypto_deposit(self, df, filename):
        self._parse_crypto_transfer(df, filename, "DEPOSIT")

    def _parse_crypto_withdraw(self, df, filename):
        self._parse_crypto_transfer(df, filename, "WITHDRAW")

    def _parse_crypto_transfer(self, df, filename, kind: str):
        tz = _timezone_hint(filename)
        for idx, row in df.iterrows():
            if not self._ok(row):
                continue
            fecha = _date(row["Tiempo"])
            asset = _text(row["Moneda"]).upper()
            qty = _decimal(row["Cantidad"], field="Cantidad")
            fee = _decimal(row.get("Tarifa", 0), field="Tarifa")
            txid = _text(row.get("TXID", ""))
            eid = _event_id(f"crypto_{kind.lower()}", txid or idx, fecha, asset, qty, fee)
            self._add_event(BinanceCanonicalEvent(
                eid, f"crypto_{kind.lower()}", fecha, f"TRANSFER_{kind}",
                asset if kind == "WITHDRAW" else "", qty if kind == "WITHDRAW" else Decimal("0"),
                asset if kind == "DEPOSIT" else "", qty if kind == "DEPOSIT" else Decimal("0"),
                asset if kind == "WITHDRAW" and fee else "", fee,
                None, "NO_APLICA", txid, _text(row.get("Red", "")), tz,
            ))
            signed = float(qty if kind == "DEPOSIT" else -qty)
            self.movimientos.append(OperacionMovimiento(
                fecha, kind, asset, signed, txid,
            ))
            if kind == "WITHDRAW" and fee:
                self.advertencias.append(
                    f"{fecha} | Retiro {asset}: la comisión de red se conserva en la trazabilidad "
                    "y requiere conciliación con el destino antes de atribuir efecto fiscal."
                )

    def _parse_fiat_deposit(self, df, filename):
        self._parse_fiat_cash(df, filename, "FIAT_DEPOSIT")

    def _parse_fiat_withdraw(self, df, filename):
        self._parse_fiat_cash(df, filename, "FIAT_WITHDRAW")

    def _parse_fiat_cash(self, df, filename, kind: str):
        tz = _timezone_hint(filename)
        value_col = "Importe de depósito" if kind == "FIAT_DEPOSIT" else "Importe de retiro"
        for idx, row in df.iterrows():
            if not self._ok(row):
                continue
            fecha = _date(row["Tiempo"])
            qty, asset = _amount_asset(row[value_col], field=value_col)
            ref = _text(row.get("ID de transacción", idx))
            eid = _event_id(kind.lower(), ref, fecha, qty, asset)
            self._add_event(BinanceCanonicalEvent(
                eid, kind.lower(), fecha, kind,
                asset if kind == "FIAT_WITHDRAW" else "", qty if kind == "FIAT_WITHDRAW" else Decimal("0"),
                asset if kind == "FIAT_DEPOSIT" else "", qty if kind == "FIAT_DEPOSIT" else Decimal("0"),
                "", Decimal("0"), None, "NO_APLICA", ref, "", tz,
            ))
            self.movimientos.append(OperacionMovimiento(
                fecha, kind, asset, float(qty if kind == "FIAT_DEPOSIT" else -qty), ref,
            ))

    def _parse_spot_order(self, df, filename):
        # Reconciliation only. A Spot Orders file without Spot Trades is unsafe.
        if "spot_trade" not in self._specialized_families:
            self._gap("spot_orders_without_trades", "spot_order", "",
                      "Se han aportado órdenes Spot pero falta Historial de operaciones Spot (fills y comisiones).")

    def _parse_convert_recurring(self, df, filename):
        # Empty exports are ignored earlier. Non-empty support needs a real schema case.
        self._gap("convert_recurring_unsupported", "convert_recurring", "",
                  "Compras recurrentes Convert requieren soporte específico antes de emitir el informe.")

    def _parse_fiat_exchange(self, df, filename):
        self._gap("fiat_exchange_unsupported", "fiat_exchange", "",
                  "Intercambios fiat requieren soporte específico antes de emitir el informe.")

    def _parse_transaction_history(self, df, filename):
        # Specialized data is canonical. TX remains complementary for legacy rewards/Earn etc.
        # Header aliases from PR #192 are applied locally by ClasificadorBinanceTx.
        legacy = ClasificadorBinanceTx(self.filepaths[self.filenames.index(filename)]).clasificar()
        specialized_present = bool(self._specialized_families)

        # Direct economic trades from TX are fallback only when specialized files are absent.
        # Even then, only direct-EUR operations with no unresolved fee may reach MotorFIFO.
        if not specialized_present:
            for op in legacy.compraventas:
                if str(op.contraparte).upper() != "EUR":
                    self._gap("legacy_trade_non_eur", "transaction_history", op.fecha,
                              f"Operación legacy {op.activo}/{op.contraparte} sin valoración EUR acreditada.")
                    continue
                if float(getattr(op, "fee_cantidad", 0) or 0) != 0:
                    self._gap("legacy_trade_fee", "transaction_history", op.fecha,
                              "Comisión legacy Binance sin tratamiento fiscal completo.")
                    continue
                self.compraventas.append(op)
            for op in legacy.swaps:
                self._gap("legacy_swap_unvalued", "transaction_history", op.fecha,
                          f"Permuta legacy {op.activo_entregado}→{op.activo_recibido} sin valoración EUR acreditada.")
        # Rewards and movements remain complementary because specialized Spot/Convert/Fiat
        # do not cover Earn or generic account events. Legacy rewards do not carry a
        # transaction-time EUR valuation, therefore they are retained for provenance but block IRPF.
        self.rendimientos.extend(legacy.rendimientos)
        if legacy.rendimientos:
            first_date = getattr(legacy.rendimientos[0], "fecha", "")
            self._gap("legacy_income_unvalued", "transaction_history", str(first_date),
                      "Rendimientos Binance sin valoración EUR verificable a la fecha de percepción.")
        self.movimientos.extend(legacy.movimientos)

        for unknown in legacy.desconocidas:
            self.desconocidas.append(unknown)
        if legacy.advertencias:
            self.advertencias.extend(legacy.advertencias)

    def validar_aceptacion(self):
        if self.bloqueos_valoracion:
            codes = ", ".join(sorted({g.code for g in self.bloqueos_valoracion}))
            raise ValueError(
                "Datos fiscales no seguros: Binance contiene operaciones sin valoración EUR "
                f"verificable o fuentes incompletas ({codes}). No se puede emitir un informe parcial."
            )
        if self.desconocidas:
            raise ValueError(
                "Datos fiscales no seguros: Binance contiene operaciones no interpretadas "
                "que pueden alterar el FIFO o la renta. No se puede emitir un informe parcial."
            )
