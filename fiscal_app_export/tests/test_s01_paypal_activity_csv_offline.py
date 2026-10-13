"""S01-G05 synthetic PayPal CSV privacy/format regression; no real report."""
from __future__ import annotations

import csv
import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "s01_paypal_activity_csv_offline.py"
spec = importlib.util.spec_from_file_location("s01_paypal_activity_csv_offline", SCRIPT)
reader = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reader)

COLUMNS = [
    "Date", "Time", "TimeZone", "Name", "Type", "Status", "Currency",
    "Gross", "Fee", "Net", "From Email Address", "To Email Address",
    "Transaction ID", "Reference Txn ID", "Balance Impact",
    "Transaction Event Code",
]


def make_csv(tmp_path, rows, columns=COLUMNS):
    file = tmp_path / "private-paypal-activity.csv"
    with file.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for r in rows:
            writer.writerow(r)
    file.chmod(0o600)
    return file


def make_row(**changes):
    fields = {
        "Date": "10/10/2026", "Time": "00:01:02", "TimeZone": "CEST",
        "Name": "PRIVATE EXAMPLE BUYER", "Type": "Generic Payment",
        "Status": "Completed", "Currency": "EUR",
        "Gross": "100.00", "Fee": "-2.00", "Net": "98.00",
        "From Email Address": "not-to-be-logged@example.invalid",
        "To Email Address": "merchant-private@example.invalid",
        "Transaction ID": "PRIVATE_SYNTH_TX_1", "Reference Txn ID": "",
        "Balance Impact": "Credit", "Transaction Event Code": "T0006",
    }
    fields.update(changes)
    return fields


def test_aggregate_only_privacy_no_identifiers(tmp_path):
    file = make_csv(tmp_path, [
        make_row(),
        make_row(**{
            "Transaction ID": "PRIVATE_SYNTH_TX_2",
            "Status": "Pending", "Currency": "USD",
            "Balance Impact": "Memo", "Transaction Event Code": "",
            "Reference Txn ID": "PRIVATE_SYNTH_TX_1",
        }),
        make_row(**{
            "Transaction ID": "PRIVATE_SYNTH_TX_1",
            "Status": "Refunded", "Balance Impact": "Debit",
        }),
        make_row(**{
            "Transaction ID": "",
            "Status": "Unverified", "Balance Impact": "",
        }),
    ])
    values = reader.summarize_report(file)
    assert values == {
        "filas": 4, "ids_transaccion_distintos": 2,
        "sin_id_transaccion": 1, "grupos_id_repetido": 1,
        "estado_completed": 1, "estado_pendiente_o_procesando": 1,
        "estado_reversado_reembolsado_u_otro_cierre": 1, "estado_otros": 1,
        "impacto_saldo_credito_debito": 2, "impacto_saldo_memo": 1,
        "impacto_saldo_no_identificado": 1, "divisa_eur": 3,
        "divisa_otra_o_ausente": 1, "tcode_formato_reconocido": 3,
        "tcode_ausente_o_no_reconocido": 1, "con_referencia_relacionada": 1,
    }
    assert all(type(v) is int for v in values.values())
    text = repr(values)
    for forbidden in ("PRIVATE_SYNTH", "EXAMPLE BUYER", "@", "100.00", "T0006"):
        assert forbidden not in text


def test_blank_report_not_evidence_of_no_paypal_activity(tmp_path):
    file = make_csv(tmp_path, [])
    result = reader.summarize_report(file)
    assert result["filas"] == 0
    assert all(n == 0 for n in result.values())


def test_rejects_incomplete_headers_and_duplicate_columns(tmp_path):
    file = make_csv(tmp_path, [make_row()], columns=["Date", "Transaction ID"])
    with pytest.raises(reader.PrivateReportError, match="Columnas"):
        reader.summarize_report(file)
    file = make_csv(tmp_path, [make_row()], columns=COLUMNS + ["Date"])
    with pytest.raises(reader.PrivateReportError, match="Columnas"):
        reader.summarize_report(file)


def test_rejects_symlink_nonprivate_and_relative_csv(tmp_path):
    file = make_csv(tmp_path, [make_row()])
    file.chmod(0o644)
    with pytest.raises(reader.PrivateReportError, match="0600"):
        reader.summarize_report(file)
    file.chmod(0o600)
    alias = tmp_path / "alias.csv"
    alias.symlink_to(file)
    with pytest.raises(reader.PrivateReportError, match="enlaces"):
        reader.summarize_report(alias)
    with pytest.raises(reader.PrivateReportError, match="absoluta"):
        reader.summarize_report(Path("private-paypal-activity.csv"))


def test_rejects_unparseable_csv_row(tmp_path):
    file = make_csv(tmp_path, [make_row()])
    with file.open("a", encoding="utf-8") as f:
        f.write('one,two,three,four,five,six,seven,eight,nine,ten,eleven,twelve,thirteen,fourteen,fifteen,sixteen,seventeen\n')
    with pytest.raises(reader.PrivateReportError, match="columnas extra"):
        reader.summarize_report(file)


def test_rejects_invalid_utf8_even_with_header(tmp_path):
    file = make_csv(tmp_path, [make_row()])
    with file.open("ab") as f:
        f.write(b"\xff\xff")
    with pytest.raises(reader.PrivateReportError, match="UTF-8"):
        reader.summarize_report(file)


def test_rejects_csv_under_repo_root(tmp_path, monkeypatch):
    file = make_csv(tmp_path, [make_row()])
    monkeypatch.setattr(reader, "ROOT", tmp_path)
    with pytest.raises(reader.PrivateReportError, match="repositorio"):
        reader.summarize_report(file)
