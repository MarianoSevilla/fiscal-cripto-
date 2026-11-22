"""Comparación adversarial de traslados Earn sin recompensas.

Nunca se utilizan movimientos de usuarios: todo es inventado.
"""
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from binance_earn_transfer_only import (
    BinancePrincipalOnlyAudit, validate_principal_only_motor,
)
from motor_fifo import MotorFIFO


def book_and_evidence():
    m = MotorFIFO()
    m.registrar_compra("2024-06-01 10:00:00", "XRP", 10, 20, "EUR", "EUR", 0)
    m.registrar_venta("2025-06-01 10:00:00", "XRP", 4, 12, "EUR", "EUR", 0)
    evidence = BinancePrincipalOnlyAudit(
        transfer_events=2, spot_trades=2, assets=("XRP",),
        sold=(("2025-06-01 10:00:00", "XRP", Decimal("4"), Decimal("8")),),
        remaining=(("XRP", Decimal("6"), Decimal("12")),),
    )
    return m, evidence


def test_decimal_book_matches_independent_fifo_motor():
    m, ev = book_and_evidence()
    validate_principal_only_motor(ev, m)


def test_wrong_fifo_cost_is_not_authorized():
    m, ev = book_and_evidence()
    altered = replace(ev, sold=((
        "2025-06-01 10:00:00", "XRP", Decimal("4"), Decimal("9")),))
    with pytest.raises(ValueError, match="coste FIFO"):
        validate_principal_only_motor(altered, m)


def test_wrong_disposition_units_and_order_are_not_authorized():
    m, ev = book_and_evidence()
    altered = replace(ev, sold=((
        "2025-06-01 10:00:00", "XRP", Decimal("5"), Decimal("8")),))
    with pytest.raises(ValueError, match="coste FIFO"):
        validate_principal_only_motor(altered, m)


def test_wrong_wallet_position_cost_is_not_authorized():
    m, ev = book_and_evidence()
    altered = replace(ev, remaining=((
        "XRP", Decimal("6"), Decimal("13")),))
    with pytest.raises(ValueError, match="saldo o coste"):
        validate_principal_only_motor(altered, m)


def test_wrong_wallet_quantity_is_not_authorized():
    m, ev = book_and_evidence()
    altered = replace(ev, remaining=((
        "XRP", Decimal("7"), Decimal("12")),))
    with pytest.raises(ValueError, match="saldo o coste"):
        validate_principal_only_motor(altered, m)


def test_verificador_principal_ejecuta_traslados_referenciados_sin_crear_lotes():
    """El verificador debe ejecutar realmente Spot->Earn->Spot y comprobar FIFO.

    La ruta de emisión sigue bloqueada: esta prueba acredita únicamente
    neutralidad de transferencias con compras EUR sintéticas.
    """
    from types import SimpleNamespace
    from binance_earn_inventory import conciliar_earn_con_ledger
    from binance_earn_rewards import reconcile_earn_rewards
    from binance_earn_transfer_only import verify_principal_only_earn

    events = [
        SimpleNamespace(
            source="earn_flexible_subscription",
            original_time="2024-02-01 10:00:00", precision="second",
            asset="ABC", amount=Decimal("6"), kind="Manual",
            origin="SPOT", destination="Earn Flexible",
        ),
        SimpleNamespace(
            source="earn_flexible_redemption",
            original_time="2024-03-01 10:00:00", precision="second",
            asset="ABC", amount=Decimal("6"), kind="Manual",
            origin="Earn Flexible", destination="SPOT",
        ),
    ]
    rows = [
        {
            "operación": "Simple Earn Flexible Subscription",
            "tiempo": "2024-02-01 10:00:00",
            "moneda": "ABC", "cambio": "-6", "cuenta": "Spot",
        },
        {
            "operación": "Simple Earn Flexible Redemption",
            "tiempo": "2024-03-01 10:00:00",
            "moneda": "ABC", "cambio": "6", "cuenta": "Spot",
        },
    ]
    principal = conciliar_earn_con_ledger(events, rows)
    rewards, candidates = reconcile_earn_rewards(events, rows)
    assert principal.instant_reconciled
    assert principal.native_events == principal.ledger_events == 2
    assert rewards.native_records == rewards.ledger_records == 0
    assert candidates == ()

    def trade(stamp, given_asset, given, received_asset, received, source):
        return SimpleNamespace(
            source=source, local_time=stamp,
            given_asset=given_asset, given_amount=Decimal(given),
            received_asset=received_asset, received_amount=Decimal(received),
            fee_asset="EUR", fee_amount=Decimal("0"),
        )

    spot = [
        trade("2024-01-01 09:00:00", "EUR", "20", "ABC", "10", "Spot BUY"),
        trade("2025-04-01 09:00:00", "ABC", "4", "EUR", "12", "Spot SELL"),
    ]
    classifier = SimpleNamespace(
        earn_events=events,
        _sections={
            "earn_flexible_rewards": SimpleNamespace(
                detectado=True, registros=0, vacio=True
            ),
        },
        earn_reconciliation=principal,
        earn_reward_reconciliation=rewards,
        fuentes_materiales_no_soportadas=[
            "earn_flexible_requiere_inventario_y_valoracion_fiscal",
        ],
        swaps=(), rendimientos=(), desconocidas=(),
        comisiones_pendientes=(), valoraciones_pendientes=(),
        _source_rows={"transaction_history": [(row, "synthetic.csv")
                                              for row in rows]},
        intercambios_nativos=spot,
        compraventas=[object(), object()],
    )
    audit = verify_principal_only_earn(classifier)
    assert audit is not None
    assert audit.transfer_events == 2
    assert audit.spot_trades == 2
    assert audit.sold == (
        ("2025-04-01 09:00:00", "ABC", Decimal("4"), Decimal("8")),
    )
    assert audit.remaining == (("ABC", Decimal("6"), Decimal("12")),)
    assert audit.fiscal_ready is False

    motor = MotorFIFO()
    motor.registrar_compra("2024-01-01 09:00:00", "ABC", 10, 20, "EUR", "EUR", 0)
    motor.registrar_venta("2025-04-01 09:00:00", "ABC", 4, 12, "EUR", "EUR", 0)
    validate_principal_only_motor(audit, motor)


def test_verificador_principal_rechaza_reparto_spot_funding_desconocido():
    from types import SimpleNamespace
    from binance_earn_transfer_only import verify_principal_only_earn

    evento = SimpleNamespace(
        source="earn_flexible_subscription",
        original_time="2024-02-01 10:00:00", precision="second",
        asset="ABC", amount=Decimal("6"), kind="Manual",
        origin="SPOT + FUNDING", destination="Earn Flexible",
    )
    classifier = SimpleNamespace(earn_events=[evento])
    assert verify_principal_only_earn(classifier) is None
