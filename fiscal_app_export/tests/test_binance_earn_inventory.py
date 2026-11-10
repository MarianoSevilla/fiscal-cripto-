"""Conciliación Earn y lotes: datos sintéticos, sin transacciones reales."""
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from binance_earn_inventory import (
    BinanceEarnInventoryError, BinanceFungibleInventory,
    conciliar_earn_con_ledger,
)


def native(direction, stamp, asset, qty, *, origin="SPOT", destination="SPOT"):
    return SimpleNamespace(
        source=f"earn_flexible_{direction}", original_time=stamp,
        asset=asset, amount=Decimal(qty), origin=origin, destination=destination,
    )


def tx(direction, stamp, asset, qty, *, wallet="Spot"):
    op = ("Simple Earn Flexible Subscription" if direction == "subscription"
          else "Simple Earn Flexible Redemption")
    amount = -Decimal(qty) if direction == "subscription" else Decimal(qty)
    return {"operación": op, "tiempo": stamp, "moneda": asset,
            "cambio": str(amount), "cuenta": wallet}


def test_subscripciones_redenciones_por_dia_sin_inventar_hora():
    events = [
        native("subscription", "2024-12-19 20:09:00", "XRP", "119"),
        native("redemption", "2025-02-02 11:02:01", "XRP", "50"),
    ]
    ledger = [
        tx("subscription", "2024-12-19 20:09:03", "XRP", "119"),
        tx("redemption", "2025-02-02 11:02:01", "XRP", "50"),
    ]
    report = conciliar_earn_con_ledger(events, ledger)
    assert report.ledger_events == report.native_events == 2
    assert report.matched_to_second == 1
    assert report.matched_same_day == 1
    assert report.quantities_reconciled is True
    assert report.instant_reconciled is False
    assert report.fiscal_ready is False


def test_earn_duplicados_preservados_y_ambiguedad_intradia():
    event = native("subscription", "2024-01-01 12:00:00", "BTC", "0.00001")
    row = tx("subscription", "2024-01-01 12:00:09", "BTC", "0.00001")
    result = conciliar_earn_con_ledger([event, event], [row, row])
    assert result.native_events == result.ledger_events == 2
    assert result.matched_same_day == 2
    assert result.ambiguous_same_day == 2
    assert not result.instant_reconciled


def test_earn_fuentes_incompletas_no_se_ocultan():
    e = native("subscription", "2024-01-01 12:00:00", "BTC", "1")
    r = conciliar_earn_con_ledger([e], [])
    assert r.native_unmatched == 1
    assert r.ledger_unmatched == 0
    assert not r.quantities_reconciled


def test_earn_cantidades_desiguales_no_se_ajustan_por_tolerancia():
    e = native("subscription", "2024-01-01 12:00:00", "BTC", "1.00000001")
    t = tx("subscription", "2024-01-01 12:00:00", "BTC", "1")
    r = conciliar_earn_con_ledger([e], [t])
    assert r.native_unmatched == r.ledger_unmatched == 1


def test_earn_origen_spot_funding_no_se_asigna_a_spot():
    e = native("subscription", "2024-01-01 12:00:00", "BTC", "1",
               origin="SPOT + FUNDING")
    t = tx("subscription", "2024-01-01 12:00:00", "BTC", "1")
    r = conciliar_earn_con_ledger([e], [t])
    assert r.quantities_reconciled
    assert r.mixed_or_unknown_origin == 1
    assert not r.instant_reconciled


def test_lote_global_sobrevive_spot_earn_y_al_cambio_de_ejercicio():
    book = BinanceFungibleInventory()
    book.acquire(
        asset="XRP", quantity="119", acquired_at="2024-12-19 16:18:00",
        wallet="SPOT", reference="synthetic-spot-001", cost_eur="250",
    )
    original = book.lots("XRP")
    book.transfer(
        asset="XRP", quantity="119", timestamp="2024-12-19 20:09:00",
        origin="SPOT", destination="EARN_FLEXIBLE",
    )
    book.transfer(
        asset="XRP", quantity="50", timestamp="2025-02-02 11:02:01",
        origin="EARN_FLEXIBLE", destination="SPOT",
    )
    assert book.wallet_balance("SPOT", "XRP") == Decimal("50")
    assert book.wallet_balance("EARN_FLEXIBLE", "XRP") == Decimal("69")
    assert book.lots("XRP") == original
    assert original[0].acquired_at.startswith("2024")
    assert original[0].cost_eur == Decimal("250")
    assert book.conserved("XRP")
    assert book.fiscal_ready is False


def test_lote_de_recompensa_sin_valorar_no_se_confunde_con_coste_cero():
    book = BinanceFungibleInventory()
    book.acquire(
        asset="BTC", quantity="0.001", acquired_at="2024-12-31 12:00:00",
        wallet="EARN_FLEXIBLE", reference="synthetic-reward",
        cost_eur=None,
    )
    assert book.lots("BTC")[0].cost_eur is None
    assert book.conserved("BTC")
    assert not book.fiscal_ready


def test_transferencia_sin_saldo_no_modifica_lotes_ni_billeteras():
    book = BinanceFungibleInventory()
    book.acquire(
        asset="ABC", quantity="1", acquired_at="2024-01-01 00:00:00",
        wallet="SPOT", reference="synthetic-1",
    )
    with pytest.raises(BinanceEarnInventoryError, match="insuficiente"):
        book.transfer(asset="ABC", quantity="2", timestamp="2025-01-01 00:00:00",
                      origin="SPOT", destination="EARN_FLEXIBLE")
    assert book.wallet_balance("SPOT", "ABC") == Decimal(1)
    assert book.wallet_balance("EARN_FLEXIBLE", "ABC") == Decimal(0)
    assert len(book.lots("ABC")) == 1


@pytest.mark.parametrize("bad", ["NaN", "Infinity", "-1", "0", "not-a-number", 0.1])
def test_cantidades_ilegales_rechazadas_sin_mutacion(bad):
    book = BinanceFungibleInventory()
    with pytest.raises(BinanceEarnInventoryError):
        book.acquire(asset="BTC", quantity=bad,
                     acquired_at="2024-01-01 00:00:00", wallet="SPOT",
                     reference="synthetic-bad")
    assert book.lots("BTC") == ()


def test_lote_no_se_duplica_si_referencia_se_repite():
    book = BinanceFungibleInventory()
    book.acquire(asset="BTC", quantity="2",
                 acquired_at="2024-01-01 00:00:00", wallet="SPOT",
                 reference="synthetic-1")
    with pytest.raises(BinanceEarnInventoryError, match="repetida"):
        book.acquire(asset="BTC", quantity="2",
                     acquired_at="2024-01-01 00:00:01", wallet="SPOT",
                     reference="synthetic-1")
    assert book.lots("BTC")[0].quantity == Decimal("2")
    assert len(book.lots("BTC")) == 1


def test_lotes_globales_no_se_asignan_a_billetera_que_no_custodia():
    book = BinanceFungibleInventory()
    book.acquire(asset="BTC", quantity="1",
                 acquired_at="2024-01-01 00:00:00", wallet="FUNDING",
                 reference="synthetic-fund")
    with pytest.raises(BinanceEarnInventoryError, match="insuficiente"):
        book.transfer(asset="BTC", quantity="1",
                      timestamp="2024-01-01 00:00:01",
                      origin="SPOT", destination="EARN_FLEXIBLE")
    assert book.conserved("BTC")


def test_earn_signos_invalidos_se_rechazan():
    with pytest.raises(BinanceEarnInventoryError, match="Dirección"):
        conciliar_earn_con_ledger([], [tx("subscription",
                          "2024-01-01 00:00:00", "BTC", "-1")])
