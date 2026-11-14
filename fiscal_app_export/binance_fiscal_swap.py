"""Aplicación aislada de permuta Binance con valoración de ambos mercados.

NO está conectada al endpoint de informes: se requiere evidencia verificable
para todas las operaciones, comisiones, inventario y los 12 ZIP completos antes
de sustituir el cálculo de permutas genérico. No modifica otros exchanges.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from binance_eur_valuation import (
    BinancePriceEvidenceError, SwapEURValuation, binance_export_time_to_utc,
)
from motor_fifo import Lote, MotorFIFO


def aplicar_permuta_binance_valorada(
    motor: MotorFIFO, *, fecha_local: str, export_filename: str,
    given_asset: str, given_amount: Decimal,
    received_asset: str, received_amount: Decimal,
    valuation: SwapEURValuation,
    fee_amount: Decimal,
    nota: str = "Binance permuta con precios históricos acreditados",
) -> None:
    """Registra una permuta EUR justificada como consumo FIFO + nuevo lote.

    La fecha, activos y cantidades deben reproducir exactamente el hecho
    económico original; una comisión sin valoración/disposición integrada
    impide la contabilización. No se asigna coste FIFO como FMV ni paridad.
    """
    if not isinstance(motor, MotorFIFO) or not isinstance(valuation, SwapEURValuation):
        raise BinancePriceEvidenceError("Motor o valoración de permuta inválidos")
    occurred_at = binance_export_time_to_utc(fecha_local, export_filename)
    if occurred_at != valuation.at_utc:
        raise BinancePriceEvidenceError("El instante de la cotización no coincide con la operación")
    if given_asset.upper() != valuation.given.asset or received_asset.upper() != valuation.received.asset:
        raise BinancePriceEvidenceError("Activos de cotización distintos de los intercambiados")
    try:
        given_amount = Decimal(str(given_amount))
        received_amount = Decimal(str(received_amount))
        fee_amount = Decimal(str(fee_amount))
    except Exception as exc:
        raise BinancePriceEvidenceError("Cantidades de permuta no interpretables") from exc
    if (
        not given_amount.is_finite() or not received_amount.is_finite()
        or given_amount <= 0 or received_amount <= 0
        or given_amount != valuation.given_amount
        or received_amount != valuation.received_amount
    ):
        raise BinancePriceEvidenceError("Cantidades de valoración distintas del hecho económico")
    if not fee_amount.is_finite() or fee_amount != 0:
        raise BinancePriceEvidenceError(
            "Comisión de permuta no contabilizada; no se permite aplicar valoración"
        )
    if (
        not valuation.given.path or not valuation.received.path
        or valuation.given_value_eur != given_amount * valuation.given.unit_price_eur
        or valuation.received_value_eur != received_amount * valuation.received.unit_price_eur
    ):
        raise BinancePriceEvidenceError(
            "Valoración de mercado sin evidencia o importes EUR inconsistentes"
        )
    if valuation.fiscal_value_eur != max(
        valuation.given_value_eur, valuation.received_value_eur
    ):
        raise BinancePriceEvidenceError("Valor fiscal EUR no sigue el máximo de mercado")
    if valuation.fiscal_value_eur <= 0:
        raise BinancePriceEvidenceError("Valor fiscal EUR inválido")

    # No registrar adquisición cuando no existe inventario de lo entregado;
    # el motor genérico podría fabricar un lote de coste sin transmisión.
    numeric_given = float(given_amount)
    numeric_received = float(received_amount)
    numeric_value = float(valuation.fiscal_value_eur)
    motor._finite(numeric_given, numeric_received, numeric_value)
    # Las cantidades de inventario han de sobrevivir EXACTAMENTE el
    # round-trip de float; una pérdida allí alteraría el número de unidades.
    # El precio EUR procedente de un par inverso (p.ej. EURUSDC) puede tener
    # expansión decimal periódica y no es representable exactamente en float.
    # Permitir SOLO diferencias de valor fiscal submicroscópicas que no
    # alteren un céntimo, ni individualmente ni acumuladas en la petición.
    # Conservar la evidencia Decimal completa en _binance_verified_swaps.
    if (Decimal(str(numeric_given)) != given_amount
            or Decimal(str(numeric_received)) != received_amount):
        raise BinancePriceEvidenceError(
            "Cantidad de permuta pierde precisión en el motor FIFO actual"
        )
    from decimal import ROUND_HALF_UP
    exact_eur = valuation.fiscal_value_eur
    bridged_eur = Decimal(str(numeric_value))
    bridge_delta = abs(bridged_eur - exact_eur)
    total_bridge_delta = getattr(
        motor, "_binance_bridge_cumulative_delta_eur", Decimal("0")
    )
    if (bridge_delta > Decimal("0.0000000001")
            or total_bridge_delta + bridge_delta > Decimal("0.00000001")
            or exact_eur.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            != bridged_eur.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)):
        raise BinancePriceEvidenceError(
            "Valor EUR de permuta pierde precisión fiscal en el motor FIFO actual"
        )
    dt = motor._parsear_fecha(fecha_local)
    lots = motor.inventario.get(given_asset.upper(), ())
    if not lots:
        raise BinancePriceEvidenceError("Permuta sin inventario previo acreditado")

    # _consumir_fifo modifica los lotes a medida que avanza. Comprobar antes
    # que el inventario es suficiente y que no contiene lotes futuros evita
    # un rechazo con inventario parcialmente consumido.
    if any(lot.cantidad_restante > 0 and lot.fecha > dt for lot in lots):
        raise BinancePriceEvidenceError(
            "Permuta con inventario posterior a la operación; requiere orden cronológico"
        )
    available = sum(
        (Decimal(str(lot.cantidad_restante))
         for lot in lots if lot.cantidad_restante > 0),
        Decimal("0"),
    )
    if available < given_amount:
        raise BinancePriceEvidenceError(
            "Inventario de permuta insuficiente: no se modifica ningún lote"
        )

    unit_cost = numeric_value / numeric_received
    motor._finite(unit_cost)
    result = motor._consumir_fifo(
        dt=dt, activo=given_asset.upper(), cantidad=numeric_given,
        precio_transmision=numeric_value, tipo="swap", nota=nota,
    )
    if result is None or result.inventario_incompleto:
        raise BinancePriceEvidenceError("Inventario de permuta insuficiente")
    result.activo_recibido = received_asset.upper()
    motor.resultados.append(result)
    motor.inventario[received_asset.upper()].append(Lote(
        fecha=dt, cantidad_original=numeric_received,
        cantidad_restante=numeric_received, precio_coste_unitario=unit_cost,
        contraparte=given_asset.upper(), origen="binance_swap_valued",
    ))
    motor._binance_bridge_cumulative_delta_eur = (
        total_bridge_delta + bridge_delta
    )
