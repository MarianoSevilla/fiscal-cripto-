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
    fee_amount: Decimal = Decimal("0"),
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
    if not motor.inventario.get(given_asset.upper()):
        raise BinancePriceEvidenceError("Permuta sin inventario previo acreditado")

    dt = motor._parsear_fecha(fecha_local)
    result = motor._consumir_fifo(
        dt=dt, activo=given_asset.upper(), cantidad=numeric_given,
        precio_transmision=numeric_value, tipo="swap", nota=nota,
    )
    if result is None or result.inventario_incompleto:
        raise BinancePriceEvidenceError("Inventario de permuta insuficiente")
    result.activo_recibido = received_asset.upper()
    motor.resultados.append(result)
    unit_cost = numeric_value / numeric_received
    motor._finite(unit_cost)
    motor.inventario[received_asset.upper()].append(Lote(
        fecha=dt, cantidad_original=numeric_received,
        cantidad_restante=numeric_received, precio_coste_unitario=unit_cost,
        contraparte=given_asset.upper(), origen="binance_swap_valued",
    ))
