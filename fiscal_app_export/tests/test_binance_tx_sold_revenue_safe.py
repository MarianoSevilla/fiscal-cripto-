"""Regresiones sintéticas para ventas Binance TX: sin datos reales de usuarios.

La clasificación de una venta no implica autorización para emitir un PDF:
se mantienen los controles globales de comisiones, permutas y cobertura.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from clasificador_binance_tx import ClasificadorBinanceTx
from app import _validar_aceptacion_fifo
from motor_fifo import MotorFIFO


HEADER = "ID de usuario,Tiempo,Cuenta,Operación,Moneda,Cambio,Observación\n"


def _clasificador(tmp_path, *rows):
    ruta = tmp_path / "binance_sintetico.csv"
    ruta.write_text(HEADER + "".join(rows), encoding="utf-8")
    return ClasificadorBinanceTx(str(ruta)).clasificar()


def test_venta_eur_reconocida_sin_fee(tmp_path):
    c = _clasificador(
        tmp_path,
        "999,2025-05-01 10:00:00,Spot,Transaction Sold,BTC,-0.01,\n",
        "999,2025-05-01 10:00:00,Spot,Transaction Revenue,EUR,600,\n",
    )
    assert len(c.compraventas) == 1
    assert not c.desconocidas
    assert not c.swaps
    venta = c.compraventas[0]
    assert (venta.tipo, venta.activo, venta.contraparte) == ("VENTA", "BTC", "EUR")
    assert venta.cantidad == 0.01
    assert venta.importe == 600
    assert venta.fee_cantidad == 0


def test_venta_eur_con_comision_preserva_coste(tmp_path):
    c = _clasificador(
        tmp_path,
        "999,2025-05-01 10:00:00,Spot,Transaction Sold,BTC,-0.01,\n",
        "999,2025-05-01 10:00:00,Spot,Transaction Revenue,EUR,600,\n",
        "999,2025-05-01 10:00:00,Spot,Transaction Fee,EUR,-1.50,\n",
    )
    assert len(c.compraventas) == 1
    assert c.compraventas[0].fee_activo == "EUR"
    assert c.compraventas[0].fee_cantidad == 1.5
    assert c.compraventas[0].importe == 600
    assert not c.desconocidas
    # El control fiscal IRPF existente conserva el bloqueo de fees:
    with pytest.raises(ValueError, match="Transaction Fee"):
        _validar_aceptacion_fifo(MotorFIFO(), c)


@pytest.mark.parametrize("quote", ["USDT", "USDC", "BUSD"])
def test_venta_contra_stablecoin_no_se_interpreta_como_eur(tmp_path, quote):
    with pytest.raises(ValueError, match="valoración histórica EUR"):
        _clasificador(
            tmp_path,
            "999,2025-05-01 10:00:00,Spot,Transaction Sold,BTC,-0.01,\n",
            f"999,2025-05-01 10:00:00,Spot,Transaction Revenue,{quote},600,\n",
            f"999,2025-05-01 10:00:00,Spot,Transaction Fee,{quote},-1.5,\n",
        )


def test_comision_de_tercera_moneda_no_se_descarta(tmp_path):
    with pytest.raises(ValueError, match="comisiones"):
        _clasificador(
            tmp_path,
            "999,2025-05-01 10:00:00,Spot,Transaction Sold,BTC,-0.01,\n",
            "999,2025-05-01 10:00:00,Spot,Transaction Revenue,EUR,600,\n",
            "999,2025-05-01 10:00:00,Spot,Transaction Fee,BNB,-0.001,\n",
        )


def test_pata_suelta_sold_no_se_convierta_en_movimiento(tmp_path):
    with pytest.raises(ValueError, match="sin contrapartida"):
        _clasificador(
            tmp_path,
            "999,2025-05-01 10:00:00,Spot,Transaction Sold,BTC,-0.01,\n",
        )


def test_ventas_simultaneas_ambiguas_se_bloquean(tmp_path):
    with pytest.raises(ValueError, match="varias monedas"):
        _clasificador(
            tmp_path,
            "999,2025-05-01 10:00:00,Spot,Transaction Sold,BTC,-0.01,\n",
            "999,2025-05-01 10:00:00,Spot,Transaction Sold,ETH,-0.2,\n",
            "999,2025-05-01 10:00:00,Spot,Transaction Revenue,EUR,600,\n",
        )


def test_ventas_y_compras_simultaneas_misma_cuenta_bloqueadas(tmp_path):
    with pytest.raises(ValueError, match="mezcla compras y ventas"):
        _clasificador(
            tmp_path,
            "999,2025-05-01 10:00:00,Spot,Transaction Sold,BTC,-0.01,\n",
            "999,2025-05-01 10:00:00,Spot,Transaction Revenue,EUR,600,\n",
            "999,2025-05-01 10:00:00,Spot,Transaction Spend,EUR,-200,\n",
            "999,2025-05-01 10:00:00,Spot,Transaction Buy,ETH,0.1,\n",
        )


def test_operaciones_con_mismo_segundo_en_cuentas_distintas_se_separan(tmp_path):
    c = _clasificador(
        tmp_path,
        "999,2025-05-01 10:00:00,Spot,Transaction Sold,BTC,-0.01,\n",
        "999,2025-05-01 10:00:00,Spot,Transaction Revenue,EUR,600,\n",
        "999,2025-05-01 10:00:00,Strategy,Transaction Spend,EUR,-200,\n",
        "999,2025-05-01 10:00:00,Strategy,Transaction Buy,ETH,0.1,\n",
    )
    assert len(c.compraventas) == 2
    assert sorted(v.tipo for v in c.compraventas) == ["COMPRA", "VENTA"]
    assert not c.desconocidas


def test_eventos_no_reconocidos_no_generan_informe_parcial(tmp_path):
    c = _clasificador(
        tmp_path,
        "999,2025-05-01 10:00:00,Spot,Staking Rewards,BTC,0.001,\n",
    )
    assert c.desconocidas
    with pytest.raises(ValueError, match="Binance contiene operaciones no interpretadas"):
        _validar_aceptacion_fifo(MotorFIFO(), c)
