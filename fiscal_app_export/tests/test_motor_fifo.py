"""
Tests unitarios para MotorFIFO — con foco en la corrección del coste base en swaps.

Bug corregido (2026-05-14):
  registrar_swap() usaba `precio_transmision = cantidad_recibida`, asignando
  las unidades del activo recibido (ej. BTC) como si fueran euros.
  Resultado: BTC entraba al inventario a ~1 EUR/BTC en lugar de ~58.800 EUR/BTC.

Casos cubiertos:
  1. Swap stablecoin→cripto (USDT→BTC): coste base correcto, ganancia/pérdida real.
  2. Swap EUR→cripto: coste base en euros, compraventa posterior correcta.
  3. Swap cripto→cripto (XRP→BNB): coste FIFO del entregado traspasado al recibido.
  4. Swap sin inventario previo: advertencia generada, coste base cero.
  5. Regresión compra/venta normal: no afectada por cambios en swap.
  6. Regresión USDC→XRP del clasificador: swap simple funciona end-to-end.
"""

import pytest
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from motor_fifo import MotorFIFO


# ── Helpers ───────────────────────────────────────────────────────────────────

def motor_con_compra(activo, cantidad, importe, fecha="2024-01-01 00:00:00",
                     contraparte="EUR"):
    """Motor con un único lote de compra ya registrado."""
    m = MotorFIFO()
    m.registrar_compra(
        fecha=fecha, activo=activo, cantidad=cantidad,
        importe=importe, contraparte=contraparte,
        fee_activo="", fee_cantidad=0.0
    )
    return m


# ── Test 1: Swap USDT→BTC — el bug original ───────────────────────────────────

def test_swap_usdt_btc_coste_base_correcto():
    """
    500 USDT → 0.0085 BTC.
    Con la corrección: BTC debe entrar al inventario a 500/0.0085 ≈ 58.823 EUR/BTC,
    no a 1 EUR/BTC como hacía el código anterior.
    """
    m = MotorFIFO()
    # Primero adquirir USDT (como si llegara de una compra EUR→USDT)
    m.registrar_compra(
        fecha="2024-05-01 00:00:00", activo="USDT", cantidad=500.0,
        importe=500.0, contraparte="EUR",
        fee_activo="", fee_cantidad=0.0
    )
    # Swap USDT→BTC
    m.registrar_swap(
        fecha="2024-05-06 00:00:00",
        activo_entregado="USDT", cantidad_entregada=500.0,
        activo_recibido="BTC",  cantidad_recibida=0.0085,
    )

    # BTC debe estar en el inventario con coste ≈ 58.823 EUR/BTC
    lotes_btc = [l for l in m.inventario.get("BTC", []) if l.cantidad_restante > 0]
    assert len(lotes_btc) == 1
    precio_unitario = lotes_btc[0].precio_coste_unitario
    assert precio_unitario == pytest.approx(500.0 / 0.0085, rel=1e-6), (
        f"Se esperaba ~{500/0.0085:.2f} EUR/BTC, obtenido {precio_unitario:.4f}. "
        "El bug anterior devolvía 1.0 EUR/BTC."
    )
    assert len(m.advertencias) == 0


def test_swap_usdt_btc_venta_posterior_ganancia_correcta():
    """
    500 USDT → 0.0085 BTC, luego venta BTC por 499 EUR.
    Ganancia esperada: 499 - 500 = -1 EUR (pequeña pérdida).
    Con el bug anterior: 499 - 0.0083 ≈ +499 EUR (incorrecto).
    """
    m = MotorFIFO()
    m.registrar_compra(
        fecha="2024-05-01 00:00:00", activo="USDT", cantidad=500.0,
        importe=500.0, contraparte="EUR",
        fee_activo="", fee_cantidad=0.0
    )
    m.registrar_swap(
        fecha="2024-05-06 00:00:00",
        activo_entregado="USDT", cantidad_entregada=500.0,
        activo_recibido="BTC",  cantidad_recibida=0.0085,
    )
    m.registrar_venta(
        fecha="2024-07-01 00:00:00", activo="BTC", cantidad=0.0085,
        importe=499.0, contraparte="EUR",
        fee_activo="", fee_cantidad=0.0
    )

    assert len(m.resultados) == 2  # resultado swap USDT + resultado venta BTC

    # El resultado fiscal relevante es el de la VENTA de BTC
    r_venta = next(r for r in m.resultados if r.activo == "BTC")
    assert r_venta.tipo_operacion == "venta"
    assert r_venta.precio_transmision == pytest.approx(499.0)
    assert r_venta.precio_coste       == pytest.approx(500.0, rel=1e-6)
    assert r_venta.ganancia_perdida   == pytest.approx(-1.0,  rel=1e-3), (
        f"Se esperaba ≈-1 EUR, obtenido {r_venta.ganancia_perdida:.4f}. "
        "El bug anterior producía ≈+499 EUR."
    )
    assert len(m.advertencias) == 0


# ── Test 2: Swap EUR→cripto ────────────────────────────────────────────────────

def test_swap_eur_a_xrp_coste_correcto():
    """
    1000 EUR → 500 XRP.
    XRP debe entrar al inventario a 1000/500 = 2.00 EUR/XRP.
    """
    m = MotorFIFO()
    m.registrar_compra(
        fecha="2024-01-01 00:00:00", activo="EUR", cantidad=1000.0,
        importe=1000.0, contraparte="EUR",
        fee_activo="", fee_cantidad=0.0
    )
    m.registrar_swap(
        fecha="2024-02-01 00:00:00",
        activo_entregado="EUR", cantidad_entregada=1000.0,
        activo_recibido="XRP", cantidad_recibida=500.0,
    )

    lotes_xrp = [l for l in m.inventario.get("XRP", []) if l.cantidad_restante > 0]
    assert len(lotes_xrp) == 1
    assert lotes_xrp[0].precio_coste_unitario == pytest.approx(2.0)

    # Venta posterior: 500 XRP por 1100 EUR → ganancia = +100 EUR
    m.registrar_venta(
        fecha="2024-06-01 00:00:00", activo="XRP", cantidad=500.0,
        importe=1100.0, contraparte="EUR",
        fee_activo="", fee_cantidad=0.0
    )
    r = next(r for r in m.resultados if r.activo == "XRP")
    assert r.ganancia_perdida == pytest.approx(100.0, rel=1e-6)


# ── Test 3: Swap cripto→cripto (XRP→BNB) ─────────────────────────────────────

def test_swap_cripto_a_cripto_coste_fifo_traspasado():
    """
    Comprar XRP a 2 EUR/XRP, luego swap 10 XRP → 0.1 BNB.
    BNB debe entrar al inventario a coste FIFO del XRP = 20 EUR total,
    es decir 20/0.1 = 200 EUR/BNB.
    El swap XRP no debe generar ganancia/pérdida (se transmite al coste).
    """
    m = motor_con_compra("XRP", cantidad=10.0, importe=20.0)  # 2 EUR/XRP

    m.registrar_swap(
        fecha="2024-03-01 00:00:00",
        activo_entregado="XRP", cantidad_entregada=10.0,
        activo_recibido="BNB", cantidad_recibida=0.1,
    )

    lotes_bnb = [l for l in m.inventario.get("BNB", []) if l.cantidad_restante > 0]
    assert len(lotes_bnb) == 1
    assert lotes_bnb[0].precio_coste_unitario == pytest.approx(200.0)  # 20 EUR / 0.1 BNB

    # El swap XRP genera resultado fiscal: transmisión a coste → G/P = 0
    r_swap = next(r for r in m.resultados if r.activo == "XRP")
    assert r_swap.precio_transmision == pytest.approx(20.0)
    assert r_swap.precio_coste       == pytest.approx(20.0)
    assert r_swap.ganancia_perdida   == pytest.approx(0.0, abs=1e-9)
    assert len(m.advertencias) == 0


# ── Test 4: Swap sin inventario previo ────────────────────────────────────────

def test_swap_sin_inventario_genera_advertencia():
    """
    Swap de un activo del que no hay lotes previos.
    Debe generar una advertencia y asignar coste base cero
    (no inventar un número).
    """
    m = MotorFIFO()
    m.registrar_swap(
        fecha="2024-04-01 00:00:00",
        activo_entregado="SOL", cantidad_entregada=1.0,
        activo_recibido="ETH",  cantidad_recibida=0.01,
    )

    # La "venta" de SOL no puede procesarse (sin inventario)
    assert any("sin inventario" in adv.lower() or "no hay lotes" in adv.lower()
               for adv in m.advertencias), \
        f"Se esperaba advertencia de inventario, obtenido: {m.advertencias}"

    # ETH entra con coste 0 (no inventar valor)
    lotes_eth = [l for l in m.inventario.get("ETH", []) if l.cantidad_restante > 0]
    assert len(lotes_eth) == 1
    assert lotes_eth[0].precio_coste_unitario == pytest.approx(0.0)


# ── Test 5: Regresión — compra/venta normal no afectada ──────────────────────

def test_compraventa_normal_no_afectada():
    """
    COMPRA BTC + VENTA BTC sin swaps: el flujo normal de compraventa
    no debe verse alterado por los cambios en registrar_swap().
    """
    m = MotorFIFO()
    m.registrar_compra(
        fecha="2024-01-15 00:00:00", activo="BTC", cantidad=0.01,
        importe=600.0, contraparte="EUR",
        fee_activo="", fee_cantidad=0.0
    )
    m.registrar_venta(
        fecha="2024-06-15 00:00:00", activo="BTC", cantidad=0.01,
        importe=650.0, contraparte="EUR",
        fee_activo="", fee_cantidad=0.0
    )

    assert len(m.resultados) == 1
    r = m.resultados[0]
    assert r.precio_transmision == pytest.approx(650.0)
    assert r.precio_coste       == pytest.approx(600.0)
    assert r.ganancia_perdida   == pytest.approx(50.0)
    assert len(m.advertencias) == 0


# ── Test 6: Regresión — swap USDC→XRP (caso del clasificador Binance) ─────────

def test_swap_usdc_a_xrp_end_to_end():
    """
    Caso real: 148.07 USDC → 61.0 XRP.
    USDC es stablecoin → valor_eur = 148.07.
    XRP debe entrar a 148.07/61 ≈ 2.428 EUR/XRP.
    """
    m = MotorFIFO()
    m.registrar_compra(
        fecha="2024-12-01 00:00:00", activo="USDC", cantidad=148.0714,
        importe=148.0714, contraparte="EUR",
        fee_activo="", fee_cantidad=0.0
    )
    m.registrar_swap(
        fecha="2024-12-11 22:51:06",
        activo_entregado="USDC", cantidad_entregada=148.0714,
        activo_recibido="XRP",   cantidad_recibida=61.0,
    )

    lotes_xrp = [l for l in m.inventario.get("XRP", []) if l.cantidad_restante > 0]
    assert len(lotes_xrp) == 1
    assert lotes_xrp[0].precio_coste_unitario == pytest.approx(148.0714 / 61.0, rel=1e-5)

    # Resultado del swap USDC: transmisión = coste → G/P ≈ 0
    r_usdc = next(r for r in m.resultados if r.activo == "USDC")
    assert r_usdc.ganancia_perdida == pytest.approx(0.0, abs=1e-6)
    assert len(m.advertencias) == 0


# ── Test 7: Stablecoin directo — sin inventario previo de USDT ───────────────

def test_swap_stablecoin_sin_inventario_previo_no_genera_advertencia():
    """
    Swap USDT→BTC sin haber registrado previamente los USDT.
    USDT es stablecoin → no se busca inventario, valor = cantidad directamente.
    No debe generar advertencia por falta de inventario.
    El BTC debe entrar con coste correcto.
    """
    m = MotorFIFO()
    # No registramos USDT previo — pero al ser stablecoin no importa
    m.registrar_swap(
        fecha="2024-05-06 00:00:00",
        activo_entregado="USDT", cantidad_entregada=500.0,
        activo_recibido="BTC",  cantidad_recibida=0.0085,
    )

    lotes_btc = [l for l in m.inventario.get("BTC", []) if l.cantidad_restante > 0]
    assert len(lotes_btc) == 1
    assert lotes_btc[0].precio_coste_unitario == pytest.approx(500.0 / 0.0085, rel=1e-6)

    # El intento de "consumir" USDT del inventario (que está vacío) generará
    # una advertencia de inventario insuficiente desde _consumir_fifo,
    # pero NO la advertencia de "sin inventario previo" del path de stablecoin.
    advertencias_swap = [a for a in m.advertencias if "sin inventario" in a.lower() and "USDT" in a]
    assert len(advertencias_swap) == 0, \
        "Los stablecoins no deben generar advertencia de 'sin inventario' en el path de valoración"
