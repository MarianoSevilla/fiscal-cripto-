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


def test_disposicion_fifo_global_no_confunde_custodia_con_antiguedad():
    book = BinanceFungibleInventory()
    book.acquire(asset="BTC", quantity="1", acquired_at="2020-01-01 00:00:00",
                 wallet="EARN_FLEXIBLE", reference="synthetic-old", cost_eur="100")
    book.acquire(asset="BTC", quantity="1", acquired_at="2021-01-01 00:00:00",
                 wallet="SPOT", reference="synthetic-new", cost_eur="300")
    consumed = book.dispose(asset="BTC", quantity="0.5",
                            timestamp="2022-01-01 00:00:00", wallet="SPOT",
                            reference="synthetic-sale")
    assert len(consumed) == 1
    assert consumed[0].acquisition_reference == "synthetic-old"
    assert consumed[0].allocated_cost_eur == Decimal("50")
    assert book.lots("BTC")[0].quantity == Decimal("0.5")
    assert book.lots("BTC")[0].cost_eur == Decimal("50")
    assert book.wallet_balance("EARN_FLEXIBLE", "BTC") == Decimal("1")
    assert book.wallet_balance("SPOT", "BTC") == Decimal("0.5")
    assert book.conserved("BTC") and not book.fiscal_ready


def test_disposicion_parcial_multilote_con_coste_decimal_exacto():
    book = BinanceFungibleInventory()
    book.acquire(asset="XRP", quantity="2", acquired_at="2020-01-01 00:00:00",
                 wallet="SPOT", reference="synthetic-a", cost_eur="60")
    book.acquire(asset="XRP", quantity="3", acquired_at="2021-01-01 00:00:00",
                 wallet="SPOT", reference="synthetic-b", cost_eur="90")
    taken = book.dispose(asset="XRP", quantity="3.5",
                         timestamp="2022-01-01 00:00:00", wallet="SPOT",
                         reference="synthetic-sale")
    assert [piece.quantity for piece in taken] == [Decimal("2"), Decimal("1.5")]
    assert [piece.allocated_cost_eur for piece in taken] == [
        Decimal("60"), Decimal("45")
    ]
    assert book.lots("XRP")[0].reference == "synthetic-b"
    assert book.lots("XRP")[0].quantity == Decimal("1.5")
    assert book.lots("XRP")[0].cost_eur == Decimal("45")
    assert book.conserved("XRP")


def test_disposicion_con_coste_no_acreditado_no_lo_sustituye_por_cero():
    book = BinanceFungibleInventory()
    book.acquire(asset="BTC", quantity="2", acquired_at="2020-01-01 00:00:00",
                 wallet="SPOT", reference="synthetic-external", cost_eur=None)
    taken = book.dispose(asset="BTC", quantity="1",
                         timestamp="2021-01-01 00:00:00", wallet="SPOT",
                         reference="synthetic-sale")
    assert taken[0].allocated_cost_eur is None
    assert book.lots("BTC")[0].cost_eur is None
    assert not book.fiscal_ready


def test_disposicion_saldo_insuficiente_no_muta_lotes():
    book = BinanceFungibleInventory()
    book.acquire(asset="BTC", quantity="1", acquired_at="2020-01-01 00:00:00",
                 wallet="EARN_FLEXIBLE", reference="synthetic-earn")
    original = book.lots("BTC")
    with pytest.raises(BinanceEarnInventoryError, match="insuficiente"):
        book.dispose(asset="BTC", quantity="0.5",
                     timestamp="2021-01-01 00:00:00", wallet="SPOT",
                     reference="synthetic-sale")
    assert book.lots("BTC") == original
    assert book.wallet_balance("EARN_FLEXIBLE", "BTC") == Decimal("1")
    assert book.conserved("BTC")


def test_disposicion_orden_mismo_segundo_ambigua_no_muta_estado():
    book = BinanceFungibleInventory()
    book.acquire(asset="BTC", quantity="1", acquired_at="2021-01-01 00:00:00",
                 wallet="SPOT", reference="synthetic-a", cost_eur="100")
    book.acquire(asset="BTC", quantity="1", acquired_at="2021-01-01 00:00:00",
                 wallet="SPOT", reference="synthetic-b", cost_eur="200")
    original = book.lots("BTC")
    with pytest.raises(BinanceEarnInventoryError, match="mismo segundo"):
        book.dispose(asset="BTC", quantity="1",
                     timestamp="2021-02-01 00:00:00", wallet="SPOT",
                     reference="synthetic-sale")
    assert book.lots("BTC") == original
    assert book.wallet_balance("SPOT", "BTC") == Decimal("2")
    with pytest.raises(BinanceEarnInventoryError, match="orden temporal"):
        book.dispose(asset="BTC", quantity="2",
                     timestamp="2021-01-01 00:00:00", wallet="SPOT",
                     reference="synthetic-sale")
    assert book.lots("BTC") == original
    assert book.conserved("BTC")


def test_disposicion_lotes_mismo_segundo_completos_y_referencia_unica():
    book = BinanceFungibleInventory()
    book.acquire(asset="BTC", quantity="1", acquired_at="2021-01-01 00:00:00",
                 wallet="SPOT", reference="synthetic-a", cost_eur="100")
    book.acquire(asset="BTC", quantity="1", acquired_at="2021-01-01 00:00:00",
                 wallet="SPOT", reference="synthetic-b", cost_eur="200")
    taken = book.dispose(asset="BTC", quantity="2",
                         timestamp="2022-01-01 00:00:00", wallet="SPOT",
                         reference="synthetic-sale")
    assert sum((x.allocated_cost_eur for x in taken), Decimal(0)) == Decimal(300)
    assert book.lots("BTC") == ()
    assert book.conserved("BTC")
    with pytest.raises(BinanceEarnInventoryError, match="repetida"):
        book.dispose(asset="BTC", quantity="1",
                     timestamp="2023-01-01 00:00:00", wallet="SPOT",
                     reference="synthetic-sale")


def test_reparto_spot_funding_documentado_no_modifica_lotes():
    book = BinanceFungibleInventory()
    book.acquire(asset="BTC", quantity="4", acquired_at="2020-01-01 00:00:00",
                 wallet="SPOT", reference="synthetic-spot", cost_eur="400")
    book.acquire(asset="BTC", quantity="6", acquired_at="2021-01-01 00:00:00",
                 wallet="FUNDING", reference="synthetic-funding", cost_eur="900")
    original = book.lots("BTC")
    book.transfer_split(
        asset="BTC", quantity="5", timestamp="2022-01-01 00:00:00",
        origin_allocations={"SPOT": "2", "FUNDING": "3"},
        destination="EARN_FLEXIBLE", reference="synthetic-mixed-sub",
    )
    assert book.wallet_balance("SPOT", "BTC") == Decimal("2")
    assert book.wallet_balance("FUNDING", "BTC") == Decimal("3")
    assert book.wallet_balance("EARN_FLEXIBLE", "BTC") == Decimal("5")
    assert book.lots("BTC") == original
    assert book.conserved("BTC") and not book.fiscal_ready


@pytest.mark.parametrize("allocations,quantity,error", [
    ({"SPOT": "2", "FUNDING": "2"}, "5", "no coincide"),
    ({"SPOT": "2", "FUNDING": "5"}, "7", "insuficiente"),
    ({"SPOT": "1"}, "1", "multibilletera"),
    ({"SPOT": "2", "spot": "2"}, "4", "incompatibles"),
    ({"SPOT": "2", "FUNDING": 0.1}, "2.1", "Decimal"),
    ({"SPOT": "2", "FUNDING": "NaN"}, "5", "finita"),
])
def test_repartos_ambiguos_o_incompletos_no_mutan_estado(allocations, quantity, error):
    book = BinanceFungibleInventory()
    book.acquire(asset="BTC", quantity="3", acquired_at="2020-01-01 00:00:00",
                 wallet="SPOT", reference="synthetic-spot")
    book.acquire(asset="BTC", quantity="3", acquired_at="2021-01-01 00:00:00",
                 wallet="FUNDING", reference="synthetic-funding")
    original = book.lots("BTC")
    with pytest.raises(BinanceEarnInventoryError, match=error):
        book.transfer_split(
            asset="BTC", quantity=quantity, timestamp="2022-01-01 00:00:00",
            origin_allocations=allocations, destination="EARN_FLEXIBLE",
            reference="synthetic-mixed-sub",
        )
    assert book.lots("BTC") == original
    assert book.wallet_balance("SPOT", "BTC") == Decimal("3")
    assert book.wallet_balance("FUNDING", "BTC") == Decimal("3")
    assert book.wallet_balance("EARN_FLEXIBLE", "BTC") == Decimal("0")
    assert book.conserved("BTC")


def test_referencia_mixta_repetida_se_rechaza_sin_mutacion():
    book = BinanceFungibleInventory()
    for wallet in ("SPOT", "FUNDING"):
        book.acquire(asset="XRP", quantity="3", acquired_at="2020-01-01 00:00:00",
                     wallet=wallet, reference="synthetic-" + wallet)
    params = dict(asset="XRP", quantity="2", timestamp="2021-01-01 00:00:00",
                  origin_allocations={"SPOT": "1", "FUNDING": "1"},
                  destination="EARN_FLEXIBLE", reference="synthetic-mixed")
    book.transfer_split(**params)
    with pytest.raises(BinanceEarnInventoryError, match="repetida"):
        book.transfer_split(**params)
    assert book.wallet_balance("EARN_FLEXIBLE", "XRP") == Decimal("2")
    assert book.conserved("XRP")


def test_diferencia_intradia_con_venta_misma_moneda_se_considera_potencialmente_material():
    events = [native("subscription", "2024-08-01 11:00:01", "ABC", "10")]
    rows = [
        tx("subscription", "2024-08-01 11:00:02", "ABC", "10"),
        {"operación": "Transaction Sold", "tiempo": "2024-08-01 11:00:03",
         "moneda": "ABC", "cambio": "-2", "cuenta": "Spot"},
    ]
    report = conciliar_earn_con_ledger(events, rows)
    assert report.matched_same_day == 1
    assert report.day_only_with_other_economic_activity == 1
    assert report.day_only_without_other_economic_activity == 0
    assert not report.fiscal_ready


def test_diferencia_intradia_sin_otros_hechos_sigue_sin_autorizar_fifo():
    events = [native("redemption", "2024-08-01 11:00:01", "ABC", "10")]
    rows = [tx("redemption", "2024-08-01 11:00:02", "ABC", "10")]
    report = conciliar_earn_con_ledger(events, rows)
    assert report.day_only_with_other_economic_activity == 0
    assert report.day_only_without_other_economic_activity == 1
    assert not report.instant_reconciled and not report.fiscal_ready


def test_recompensa_del_mismo_dia_puede_afectar_orden_intradia():
    events = [
        native("subscription", "2024-08-01 11:00:01", "ABC", "10"),
        SimpleNamespace(source="earn_flexible_rewards",
                        original_time="2024-08-01", asset="ABC",
                        amount=Decimal("0.01")),
    ]
    rows = [tx("subscription", "2024-08-01 11:00:02", "ABC", "10")]
    report = conciliar_earn_con_ledger(events, rows)
    assert report.day_only_with_other_economic_activity == 1
    assert not report.fiscal_ready
