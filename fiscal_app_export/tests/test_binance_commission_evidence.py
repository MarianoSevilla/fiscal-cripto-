"""Regresiones Binance comisiones: todos los datos de prueba son sintéticos."""
from decimal import Decimal
from pathlib import Path
import csv
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from binance_commission_evidence import (
    BinanceCommissionEvidenceError, COMMISSION_OPERATIONS,
    audit_binance_commissions, is_binance_commission,
    iter_binance_commissions,
)
from clasificador_binance_multi import (
    BinanceMultiUserError, ClasificadorBinanceMulti,
)
from clasificador_binance_tx import ClasificadorBinanceTx


def row(operation="Commission History", amount="0.000000000000000001",
        wallet="Spot", asset="BNB", stamp="2021-01-04 12:13:14"):
    return {"operación": operation, "tiempo": stamp, "moneda": asset,
            "cambio": amount, "cuenta": wallet, "observación": "synthetic"}


def test_three_labels_have_distinct_evidence_and_no_tax_category():
    rows = [row(operation=op) for op in sorted(COMMISSION_OPERATIONS)]
    records = list(iter_binance_commissions(rows))
    assert len(records) == 3
    assert {r.source_operation for r in records} == COMMISSION_OPERATIONS
    assert all(r.quantity == Decimal("0.000000000000000001") for r in records)
    assert all(r.value_eur is None and r.fiscal_category is None
               and not r.fiscal_ready for r in records)
    assert all(is_binance_commission(r) for r in rows)


def test_different_wallet_and_assets_are_not_merged():
    audit = audit_binance_commissions([
        row("Referrer Commission", "0.0000000005", wallet="USD-M Futures", asset="USDT"),
        row("Commission Rebate", "0.0000000005", wallet="Spot", asset="BNB"),
    ])
    assert audit.records == 2
    assert dict(audit.quantities_by_asset) == {
        "BNB": Decimal("0.0000000005"),
        "USDT": Decimal("0.0000000005"),
    }
    assert audit.pending_eur_valuations == audit.pending_fiscal_classifications == 2
    assert not audit.fiscal_ready


def test_identical_rows_are_separate_receipts_not_deduplicated():
    a = row()
    records = list(iter_binance_commissions([a, a]))
    assert len(records) == 2
    assert [r.ordinal for r in records] == [0, 1]
    assert audit_binance_commissions([a, a]).records == 2


def test_non_commission_operations_are_never_inferred_as_referrals():
    allrows = [row("Transaction Fee", "-0.001"),
               row("Simple Earn Flexible Interest", "0.2")]
    assert list(iter_binance_commissions(allrows)) == []
    assert audit_binance_commissions(allrows).records == 0


@pytest.mark.parametrize("bad", ["NaN", "Infinity", "0", "-1", "x", 0.1, True])
def test_bad_commission_amount_fail_closed(bad):
    with pytest.raises(BinanceCommissionEvidenceError):
        list(iter_binance_commissions([row(amount=bad)]))


@pytest.mark.parametrize("stamp", ["2025-02-30 01:02:03", "2025-01-01", "x"])
def test_bad_timestamp_is_not_replaced_by_midnight(stamp):
    with pytest.raises(BinanceCommissionEvidenceError, match="Fecha"):
        list(iter_binance_commissions([row(stamp=stamp)]))


def test_large_stream_preserves_cardinality_and_decimal_precision():
    value = "0.000000000000000001"
    repeated = (row(amount=value) for _ in range(20000))
    audit = audit_binance_commissions(repeated)
    assert audit.records == 20000
    assert dict(audit.quantities_by_asset)["BNB"] == Decimal("0.000000000000020000")


def _write_csv(tmp_path, name, records):
    path = tmp_path / name
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["ID de usuario", "Tiempo", "Cuenta", "Operación",
                         "Moneda", "Cambio", "Observación"])
        for r in records:
            writer.writerow(["synthetic", r["tiempo"], r["cuenta"], r["operación"],
                             r["moneda"], r["cambio"], "synthetic"])
    return str(path)


def test_multisource_keeps_commissions_separate_and_blocks_pdf(tmp_path):
    ops = [
        row("Commission History", "0.01"),
        row("Commission Rebate", "0.02"),
        row("Referrer Commission", "0.03", wallet="USD-M Futures", asset="USDT"),
    ]
    path = _write_csv(tmp_path, "ledger.csv", ops)
    c = ClasificadorBinanceMulti([path]).clasificar()
    assert c.commission_evidence_summary.records == 3
    assert len(list(c.iter_commission_evidence())) == 3
    assert c.commission_evidence_summary.pending_eur_valuations == 3
    assert not c.rendimientos and not c.desconocidas
    assert "binance_comisiones_sin_valoracion_ni_categoria_fiscal" in (
        c.fuentes_materiales_no_soportadas)
    assert all(not ev.fiscal_ready for ev in c.iter_commission_evidence())


def test_multisource_refuses_negative_commission(tmp_path):
    path = _write_csv(tmp_path, "invalid.csv",
                      [row("Commission Rebate", "-0.02")])
    with pytest.raises(BinanceMultiUserError) as exc:
        ClasificadorBinanceMulti([path]).clasificar()
    assert exc.value.code == "invalid_binance_commission"


def test_legacy_does_not_tax_referrals_as_investment_income(tmp_path):
    ops = [row(op, "0.01") for op in COMMISSION_OPERATIONS]
    path = _write_csv(tmp_path, "legacy.csv", ops)
    parsed = ClasificadorBinanceTx(path).clasificar()
    assert not parsed.rendimientos
    assert len(parsed.desconocidas) == 3
    assert {op.subtipo for op in parsed.desconocidas} == COMMISSION_OPERATIONS


def test_eur_commission_amount_has_known_eur_value_but_not_fiscal_category():
    evidence = list(iter_binance_commissions([
        row("Commission Rebate", "0.50", asset="EUR")
    ]))
    assert len(evidence) == 1
    assert evidence[0].quantity == Decimal("0.50")
    assert evidence[0].value_eur == Decimal("0.50")
    assert evidence[0].fiscal_category is None
    report = audit_binance_commissions([
        row("Commission Rebate", "0.50", asset="EUR")
    ])
    assert report.pending_eur_valuations == 0
    assert report.pending_fiscal_classifications == 1
    assert not report.fiscal_ready


def test_big_ledger_uses_bounded_commission_memory_and_keeps_all_receipts(tmp_path):
    path = _write_csv(tmp_path, "many.csv", (
        row("Commission Rebate", "0.00000001") for _ in range(101001)
    ))
    c = ClasificadorBinanceMulti([path]).clasificar()
    assert c.resumen_archivos["transaction_history"]["registros"] == 101001
    assert c.commission_evidence_summary.records == 101001
    assert c.commission_evidence_summary.years == (2021,)
    # Las filas masivas se leen del temporal, no se materializan en memoria.
    assert c._source_rows["transaction_history"] == []
    assert sum(1 for _ in c.iter_commission_evidence()) == 101001
    assert c.commission_evidence_summary.pending_eur_valuations == 101001
    assert "binance_comisiones_sin_valoracion_ni_categoria_fiscal" in (
        c.fuentes_materiales_no_soportadas
    )


def test_duplicate_commission_across_files_blocks_without_dropping(tmp_path):
    common = [row("Referrer Commission", "0.125")]
    a = _write_csv(tmp_path, "first.csv", common)
    b = _write_csv(tmp_path, "second.csv", common)
    c = ClasificadorBinanceMulti([a,b]).clasificar()
    assert c.commission_evidence_summary.records == 2
    assert sum(1 for _ in c.iter_commission_evidence()) == 2
    assert "filas_identicas_entre_exportaciones_sin_id_unico" in (
        c.fuentes_materiales_no_soportadas
    )


def test_ledger_commission_and_economic_event_keeps_the_other_event(tmp_path):
    p = _write_csv(tmp_path, "mixed.csv", [
        row("Commission Rebate", "0.01"),
        row("Commission History", "0.02"),
        row("Referrer Commission", "0.03"),
        row("Other Unrecognized Operation", "1"),
    ])
    c = ClasificadorBinanceMulti([p]).clasificar()
    assert c.commission_evidence_summary.records == 3
    assert len(c._source_rows["transaction_history"]) == 1
    assert c.resumen_archivos["transaction_history"]["registros"] == 4
    assert len(c.desconocidas) == 1
    assert "binance_comisiones_sin_valoracion_ni_categoria_fiscal" in (
        c.fuentes_materiales_no_soportadas
    )
