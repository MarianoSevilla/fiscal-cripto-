"""Reconocimiento fail-closed de cuatro ZIP Binance Simple Earn Flexible.

Los archivos generados y movimientos de prueba son totalmente sintéticos.
No usar nunca transacciones ni cantidades privadas de usuarios como fixtures.
"""
from pathlib import Path
from decimal import Decimal
import csv
import io
import sys
import zipfile

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from binance_uploads import save_binance_uploads
from clasificador_binance_multi import (
    BinanceMultiUserError, ClasificadorBinanceMulti, detect_binance_source,
)


SUB = ["Fecha de suscripción", "Nombre del producto", "Moneda", "Cantidad",
       "Tipo", "De", "Estado"]
RED = ["Fecha de canje", "Nombre del producto", "Moneda", "Principal Reembolsado",
       "Método", "Canjear por", "Estado"]
REW = ["Tiempo", "Moneda", "Cantidad", "Tipo"]
EXC = ["Tiempo", "Moneda", "Cantidad", "A", "Estado"]
LOCK_SUB = ["Fecha de suscripción", "Moneda", "Importe total",
            "Periodo de Bloqueo", "Tipo", "De"]
LOCK_RED = ["Fecha de canje", "Moneda", "Importe de Redención",
            "Canjear por", "Hora estimada de llegada", "Estado"]
LOCK_REW = ["Tiempo", "Moneda", "Interés", "Periodo de Bloqueo", "TAE", "Tipo"]


def _fake_csv(tmp_path, name, header, rows):
    path = tmp_path / name
    with path.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.writer(fh)
        writer.writerow(header)
        writer.writerows(rows)
    return path


class _FakeUpload:
    def __init__(self, p):
        self.filename = p.name
        self._p = p

    def save(self, dest):
        Path(dest).write_bytes(self._p.read_bytes())


def _fake_zip(tmp_path, tag, header, rows):
    csv_buffer = io.StringIO(newline="")
    writer = csv.writer(csv_buffer)
    writer.writerow(header)
    writer.writerows(rows)
    target = tmp_path / f"Binance-Earn-{tag}-(UTC+1).zip"
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("part1.csv", csv_buffer.getvalue().encode("utf-8-sig"))
    return _FakeUpload(target)


def test_firmas_de_los_cuatro_earn_flexible():
    assert detect_binance_source(SUB) == "earn_flexible_subscription"
    assert detect_binance_source(RED) == "earn_flexible_redemption"
    assert detect_binance_source(REW) == "earn_flexible_rewards"
    assert detect_binance_source(EXC) == "earn_flexible_exchange"
    assert detect_binance_source(REW + ["Operación"]) == "unknown"


def test_firmas_locked_exigen_cabeceras_exactas():
    assert detect_binance_source(LOCK_SUB) == "earn_locked_subscription"
    assert detect_binance_source(LOCK_RED) == "earn_locked_redemption"
    assert detect_binance_source(LOCK_REW) == "earn_locked_rewards"
    assert detect_binance_source(LOCK_REW + ["Operación"]) == "unknown"


def test_tres_zip_locked_se_conservan_sin_identidad_billetera_ni_lote(tmp_path):
    # Filas totalmente sintéticas que siguen la estructura de las tres
    # exportaciones Binance Locked originales.
    uploads = [
        _fake_zip(tmp_path, "locked-sub", LOCK_SUB, [
            ["2021-06-01 09:10:11", "BNB", "1.25", "90 días", "Auto", "Spot"],
        ]),
        _fake_zip(tmp_path, "locked-red", LOCK_RED, [
            ["2021-09-01 10:11:12", "BNB", "1.25", "BNB", "2021-09-01 10:12:00", "Success"],
        ]),
        _fake_zip(tmp_path, "locked-reward", LOCK_REW, [
            ["2021-06-02", "BNB", "0.01", "90 días", "5.00%", "Staking Rewards"],
            ["2021-06-02", "BNB", "0.01", "90 días", "5.00%", "Staking Rewards"],
        ]),
    ]
    paths, names = save_binance_uploads(uploads)
    try:
        c = ClasificadorBinanceMulti(paths, names, final_year=2025).clasificar()
        locked = [event for event in c.earn_events if event.source.startswith("earn_locked_")]
        assert len(locked) == 4  # Filas iguales se conservan, no se deduplican.
        assert c.resumen_archivos["no_reconocidos"] == 0
        assert c.resumen_archivos["earn_locked_subscription"]["registros"] == 1
        assert c.resumen_archivos["earn_locked_redemption"]["registros"] == 1
        assert c.resumen_archivos["earn_locked_rewards"]["registros"] == 2
        assert [event.source for event in locked] == [
            "earn_locked_subscription", "earn_locked_redemption",
            "earn_locked_rewards", "earn_locked_rewards",
        ]
        assert all(event.origin == "origen no acreditado" for event in locked)
        assert all(event.destination == "destino no acreditado" for event in locked)
        assert all(event.raw_fields for event in locked)
        assert locked[0].raw_fields[2] == ("importe total", "1.25")
        assert locked[1].raw_fields[-2] == ("hora estimada de llegada", "2021-09-01 10:12:00")
        assert [event.precision for event in locked] == ["second", "second", "day", "day"]
        assert c.compraventas == [] and c.swaps == []
        assert c.rendimientos == [] and c.movimientos == []
        assert c.valoraciones_pendientes == []
        assert c.earn_reward_reconciliation.native_records == 0
        assert "earn_locked_requiere_inventario_y_valoracion_fiscal" in (
            c.fuentes_materiales_no_soportadas
        )
        assert "earn_flexible_requiere_inventario_y_valoracion_fiscal" not in (
            c.fuentes_materiales_no_soportadas
        )
    finally:
        for path in paths:
            Path(path).unlink(missing_ok=True)


def test_locked_staking_reward_no_se_identifica_con_asiento_de_ledger(tmp_path):
    locked = _fake_csv(tmp_path, "locked.csv", LOCK_REW, [
        ["2021-06-02", "BNB", "0.01", "90 días", "5.00%", "Staking Rewards"],
    ])
    ledger = _fake_csv(tmp_path, "tx.csv", [
        "ID de usuario", "Tiempo", "Cuenta", "Operación", "Moneda", "Cambio", "Observación",
    ], [
        ["synthetic", "2021-06-02 12:00:00", "Spot", "Staking Rewards", "BNB", "0.01", "synthetic"],
    ])
    c = ClasificadorBinanceMulti([str(locked), str(ledger)]).clasificar()
    assert len([event for event in c.earn_events if event.source == "earn_locked_rewards"]) == 1
    assert c.earn_reward_reconciliation.native_records == 0
    assert c.earn_reward_reconciliation.matched_exact == 0
    assert c.compraventas == [] and c.rendimientos == []


def test_cuatro_zip_earn_se_reconocen_sin_fabricar_fifo(tmp_path):
    uploads = [
        _fake_zip(tmp_path, "sub", SUB, [
            ["2025-05-03 10:00:00", "ABC", "ABC", "1,234.50000001",
             "Auto", "SPOT", "Success"],
        ]),
        _fake_zip(tmp_path, "red", RED, [
            ["2025-05-04 11:00:00", "ABC", "ABC", "12.00000001",
             "Fast redemption", "SPOT", "Success"],
        ]),
        _fake_zip(tmp_path, "reward", REW, [
            ["2025-05-03", "ABC", "0.00000001", "Real-time APR Rewards"],
            ["2025-05-04 05:00:00", "ABC", "0.00000002", "Bonus Tiered APR Rewards"],
        ]),
        _fake_zip(tmp_path, "exchange", EXC, [
            ["No hay datos que se ajusten a los criterios."],
        ]),
    ]
    paths, names = save_binance_uploads(uploads)
    try:
        c = ClasificadorBinanceMulti(paths, names).clasificar()
        assert len(c.earn_events) == 4
        assert c.resumen_archivos["no_reconocidos"] == 0
        assert c.resumen_archivos["earn_flexible_exchange"]["vacio"]
        assert c.resumen_archivos["earn_flexible_subscription"]["registros"] == 1
        assert c.resumen_archivos["earn_flexible_redemption"]["registros"] == 1
        assert c.resumen_archivos["earn_flexible_rewards"]["registros"] == 2
        assert [e.amount for e in c.earn_events] == [
            Decimal("1234.50000001"), Decimal("12.00000001"),
            Decimal("0.00000001"), Decimal("0.00000002"),
        ]
        assert [e.precision for e in c.earn_events] == [
            "second", "second", "day", "second",
        ]
        assert c.earn_events[2].destination == "Earn Flexible"
        assert c.earn_events[3].destination == "SPOT"
        assert c.compraventas == [] and c.swaps == []
        assert c.rendimientos == [] and c.movimientos == []
        assert c.valoraciones_pendientes == []
        assert "earn_flexible_requiere_inventario_y_valoracion_fiscal" in (
            c.fuentes_materiales_no_soportadas
        )
    finally:
        for p in paths:
            Path(p).unlink(missing_ok=True)


@pytest.mark.parametrize("value", ["-1", "1,23", "1,2.3", "NaN", "Infinity"])
def test_earn_cantidades_invalidas_no_se_omiten(tmp_path, value):
    path = _fake_csv(tmp_path, "reward.csv", REW, [
        ["2025-05-03", "ABC", value, "Real-time APR Rewards"],
    ])
    with pytest.raises(BinanceMultiUserError) as exc:
        ClasificadorBinanceMulti([str(path)]).clasificar()
    assert exc.value.code == "invalid_earn_amount"


def test_earn_ticker_t_y_recompensa_cero_son_validos_sin_lote_inventado(tmp_path):
    """All fixtures synthetic: a one-letter ticker and a zero rewards row."""
    sub = _fake_csv(tmp_path, "sub.csv", SUB, [
        ["2024-01-01 10:00:00", "T", "T", "2", "Auto", "SPOT", "Success"],
    ])
    rewards = _fake_csv(tmp_path, "reward.csv", REW, [
        ["2024-01-01", "T", "0", "Bonus Tiered APR Rewards"],
        ["2024-01-02", "T", "0.00000001", "Real-time APR Rewards"],
    ])
    c = ClasificadorBinanceMulti([str(sub), str(rewards)]).clasificar()
    assert len(c.earn_events) == 2
    assert all(e.asset == "T" for e in c.earn_events)
    assert [e.amount for e in c.earn_events] == [
        Decimal("2"), Decimal("0.00000001")]
    assert c.earn_zero_reward_rows == 1
    assert c.resumen_archivos["recompensas_earn_cantidad_cero"] == 1
    assert c.resumen_archivos["earn_flexible_rewards"]["registros"] == 2
    assert c.compraventas == []
    assert "earn_flexible_requiere_inventario_y_valoracion_fiscal" in (
        c.fuentes_materiales_no_soportadas
    )


@pytest.mark.parametrize("source,headers,row", [
    ("subscription", SUB,
     ["2025-05-03 10:00:00", "ABC", "ABC", "0", "Auto", "SPOT", "Success"]),
    ("redemption", RED,
     ["2025-05-03 10:00:00", "ABC", "ABC", "0", "Fast", "SPOT", "Success"]),
])
def test_earn_cantidad_cero_de_principal_sigue_rechazada(
        tmp_path, source, headers, row):
    path = _fake_csv(tmp_path, f"{source}.csv", headers, [row])
    with pytest.raises(BinanceMultiUserError) as exc:
        ClasificadorBinanceMulti([str(path)]).clasificar()
    assert exc.value.code == "invalid_earn_amount"


def test_earn_intercambio_material_no_se_ignora(tmp_path):
    path = _fake_csv(tmp_path, "exchange.csv", EXC, [
        ["2025-05-03", "ABC", "20", "DEF", "Success"],
    ])
    c = ClasificadorBinanceMulti([str(path)]).clasificar()
    assert "earn_flexible_intercambio_sin_patas_de_valoracion" in (
        c.fuentes_materiales_no_soportadas
    )
    assert c.earn_events == []


def test_earn_recompensa_fecha_solo_dia_no_tiene_hora_inventada(tmp_path):
    path = _fake_csv(tmp_path, "reward.csv", REW, [
        ["2024-12-30", "ABC", "0.00000003", "Real-time APR Rewards"],
    ])
    c = ClasificadorBinanceMulti([str(path)]).clasificar()
    assert c.earn_events[0].original_time == "2024-12-30"
    assert c.earn_events[0].precision == "day"


def test_earn_estado_desconocido_queda_bloqueado(tmp_path):
    path = _fake_csv(tmp_path, "sub.csv", SUB, [
        ["2025-05-03 10:00:00", "ABC", "ABC", "1",
         "Auto", "SPOT", "On Hold"],
    ])
    c = ClasificadorBinanceMulti([str(path)]).clasificar()
    assert c.earn_events == []
    assert "estado_no_reconocido_earn_flexible_subscription" in (
        c.fuentes_materiales_no_soportadas
    )


def test_earn_producto_ajeno_a_moneda_bloquea(tmp_path):
    path = _fake_csv(tmp_path, "sub.csv", SUB, [
        ["2025-05-03 10:00:00", "DEF", "ABC", "1",
         "Auto", "SPOT", "Success"],
    ])
    with pytest.raises(BinanceMultiUserError) as exc:
        ClasificadorBinanceMulti([str(path)]).clasificar()
    assert exc.value.code == "earn_product_asset_mismatch"


def test_earn_fuente_nativa_y_ledger_conciliacion_multianual(tmp_path):
    """El importador correlaciona las dos fuentes sin deduplicar ni crear lotes."""
    ledger = _fake_csv(tmp_path, "tx.csv", [
        "ID de usuario", "Tiempo", "Cuenta", "Operación", "Moneda",
        "Cambio", "Observación",
    ], [
        ["fake", "2024-12-19 20:09:03", "Spot",
         "Simple Earn Flexible Subscription", "XRP", "-10", "Binance Earn"],
        ["fake", "2024-12-20 10:10:00", "Spot",
         "Simple Earn Flexible Subscription", "BTC", "-0.1", "Binance Earn"],
        ["fake", "2025-01-05 12:00:01", "Spot",
         "Simple Earn Flexible Redemption", "XRP", "4", "Binance Earn"],
    ])
    sub = _fake_csv(tmp_path, "sub.csv", SUB, [
        ["2024-12-19 20:09:00", "XRP", "XRP", "10", "Auto", "SPOT", "Success"],
        ["2024-12-20 10:10:00", "BTC", "BTC", "0.1",
         "Normal", "SPOT + FUNDING", "Success"],
    ])
    red = _fake_csv(tmp_path, "red.csv", RED, [
        ["2025-01-05 12:00:01", "XRP", "XRP", "4",
         "Fast redemption", "SPOT", "Success"],
    ])
    c = ClasificadorBinanceMulti([str(sub), str(red), str(ledger)]).clasificar()
    report = c.earn_reconciliation
    assert report is not None
    assert report.ledger_events == report.native_events == 3
    assert report.matched_to_second == 2
    assert report.matched_same_day == 1
    assert report.ledger_unmatched == report.native_unmatched == 0
    assert report.mixed_or_unknown_origin == 1
    assert report.quantities_reconciled
    assert not report.instant_reconciled
    assert not report.fiscal_ready
    assert "earn_orden_intradia_o_origen_pendiente" in (
        c.fuentes_materiales_no_soportadas
    )
    assert not c.compraventas and not c.swaps
    assert len(c.movimientos) == 3


def test_earn_fuentes_desiguales_se_marcan_sin_compensar_cantidades(tmp_path):
    ledger = _fake_csv(tmp_path, "tx.csv", [
        "ID de usuario", "Tiempo", "Cuenta", "Operación", "Moneda",
        "Cambio", "Observación",
    ], [
        ["fake", "2024-12-19 20:09:03", "Spot",
         "Simple Earn Flexible Subscription", "XRP", "-10", "Binance Earn"],
    ])
    sub = _fake_csv(tmp_path, "sub.csv", SUB, [
        ["2024-12-19 20:09:03", "XRP", "XRP", "9.99999999",
         "Auto", "SPOT", "Success"],
    ])
    c = ClasificadorBinanceMulti([str(sub), str(ledger)]).clasificar()
    report = c.earn_reconciliation
    assert report.native_unmatched == report.ledger_unmatched == 1
    assert not report.quantities_reconciled
    assert "earn_fuentes_no_conciliadas" in c.fuentes_materiales_no_soportadas
    assert not c.compraventas and not c.swaps
