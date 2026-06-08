"""
Tests unitarios para ClasificadorBinanceTx.
Cubre los casos auditados el 2026-05-14:
  - Commission Rebate en EUR (valor directo conocido)
  - Commission Rebate en BNB (cantidad cripto, sin precio EUR)
  - Referrer Commission en USDT (estable)
  - Pool Distribution en LTC (cantidad cripto)
  - Transaction Buy/Spend emparejado (USDC→XRP y EUR→XRP, incluido grupo multi-fila)
  - Small Assets Exchange BNB (positive + negative = MOVIMIENTO, sin afectar FIFO)
"""

import io
import textwrap
import pytest
import pandas as pd

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from clasificador_binance_tx import ClasificadorBinanceTx, _parse_tiempo


# ── Helpers ────────────────────────────────────────────────────────────────────

def _csv_to_tmpfile(csv_text: str, tmp_path):
    """Escribe un CSV en un fichero temporal y devuelve la ruta."""
    p = tmp_path / "binance_test.csv"
    p.write_text(textwrap.dedent(csv_text).strip(), encoding="utf-8")
    return str(p)


HEADER = "ID de usuario,Tiempo,Cuenta,Operación,Moneda,Cambio,Observación\n"


# ── Test 1: Commission Rebate en EUR ───────────────────────────────────────────

def test_commission_rebate_eur(tmp_path):
    """
    Una fila de Commission Rebate en EUR con Cambio positivo.
    El campo `cantidad` debe ser el importe directo en EUR (valoración conocida).
    """
    csv = HEADER + "123,24-06-15 10:00:00,Spot,Commission Rebate,EUR,0.50,\n"
    c = ClasificadorBinanceTx(_csv_to_tmpfile(csv, tmp_path)).clasificar()

    assert len(c.rendimientos) == 1, "Debe clasificarse como RENDIMIENTO"
    r = c.rendimientos[0]
    assert r.activo    == "EUR"
    assert r.cantidad  == pytest.approx(0.50)
    assert r.subtipo   == "Commission Rebate"
    assert len(c.desconocidas) == 0


# ── Test 2: Commission Rebate en BNB ──────────────────────────────────────────

def test_commission_rebate_bnb(tmp_path):
    """
    Una fila de Commission Rebate en BNB con Cambio positivo.
    Se clasifica como RENDIMIENTO; `activo` es BNB (sin valoración EUR conocida).
    NO debe interpretarse la cantidad como euros.
    """
    csv = HEADER + "123,24-06-15 10:01:00,Spot,Commission Rebate,BNB,0.00000052,\n"
    c = ClasificadorBinanceTx(_csv_to_tmpfile(csv, tmp_path)).clasificar()

    assert len(c.rendimientos) == 1
    r = c.rendimientos[0]
    assert r.activo   == "BNB"
    assert r.cantidad == pytest.approx(0.00000052)
    # El rendimiento no tiene atributo valor_eur: no existe valoración EUR automática
    assert not hasattr(r, "valor_eur"), \
        "OperacionRendimiento no debe tener campo valor_eur para no confundir con importe EUR"
    assert len(c.desconocidas) == 0


# ── Test 3: Referrer Commission en USDT ───────────────────────────────────────

def test_referrer_commission_usdt(tmp_path):
    """
    Referrer Commission en USDT: rendimiento en estable (≈ USD, requiere conversión EUR).
    """
    csv = HEADER + "123,24-07-01 08:00:00,Spot,Referrer Commission,USDT,1.23456,ref123\n"
    c = ClasificadorBinanceTx(_csv_to_tmpfile(csv, tmp_path)).clasificar()

    assert len(c.rendimientos) == 1
    r = c.rendimientos[0]
    assert r.activo   == "USDT"
    assert r.cantidad == pytest.approx(1.23456)
    assert len(c.desconocidas) == 0


# ── Test 4: Pool Distribution en LTC ──────────────────────────────────────────

def test_pool_distribution_ltc(tmp_path):
    """
    Pool Distribution (recompensas de Binance Pool) en LTC.
    Solo puede mostrarse como cantidad de LTC recibida.
    """
    csv = HEADER + "123,24-05-01 03:18:34,Pool,Pool Distribution,LTC,0.0000038,Binance Pool\n"
    c = ClasificadorBinanceTx(_csv_to_tmpfile(csv, tmp_path)).clasificar()

    assert len(c.rendimientos) == 1
    r = c.rendimientos[0]
    assert r.activo   == "LTC"
    assert r.cantidad == pytest.approx(0.0000038)
    assert r.subtipo  == "Pool Distribution"
    assert len(c.desconocidas) == 0


# ── Test 5a: Transaction Buy/Spend — par simple USDC→XRP ─────────────────────

def test_transaction_buy_spend_usdc_xrp(tmp_path):
    """
    Un par Transaction Spend (USDC negativo) + Transaction Buy (XRP positivo)
    al mismo segundo → SWAP crypto→crypto.
    """
    csv = HEADER + (
        "123,24-12-11 22:51:06,Spot,Transaction Spend,USDC,-148.0714,\n"
        "123,24-12-11 22:51:06,Spot,Transaction Buy,XRP,61.0,\n"
        "123,24-12-11 22:51:06,Spot,Transaction Fee,BNB,-0.000149,\n"
    )
    c = ClasificadorBinanceTx(_csv_to_tmpfile(csv, tmp_path)).clasificar()

    assert len(c.swaps) == 1, "Debe generar un SWAP (USDC→XRP)"
    assert len(c.compraventas) == 0
    s = c.swaps[0]
    assert s.activo_entregado  == "USDC"
    assert s.cantidad_entregada == pytest.approx(148.0714)
    assert s.activo_recibido    == "XRP"
    assert s.cantidad_recibida  == pytest.approx(61.0)
    assert len(c.desconocidas) == 0


# ── Test 5b: Transaction Buy/Spend — EUR→XRP, grupo multi-fila ───────────────

def test_transaction_buy_spend_eur_xrp_multirow(tmp_path):
    """
    Grupo de 2025-01-08: 5 Spend EUR + 5 Buy XRP al mismo segundo.
    Binance ejecuta múltiples órdenes parciales en el mismo instante.
    Debe generar UNA sola COMPRA con el total agregado:
      - XRP recibido: 4 + 67 + 303 + 4 + 67 = 445
      - EUR pagado:  150.4887 + 8.9856 + 680.659 + 150.5088 + 8.9848 = 999.6269
    """
    csv = HEADER + (
        "123,25-01-08 17:19:04,Spot,Transaction Buy,XRP,4.0,\n"
        "123,25-01-08 17:19:04,Spot,Transaction Fee,BNB,-0.000167,\n"
        "123,25-01-08 17:19:04,Spot,Transaction Buy,XRP,67.0,\n"
        "123,25-01-08 17:19:04,Spot,Transaction Buy,XRP,303.0,\n"
        "123,25-01-08 17:19:04,Spot,Transaction Spend,EUR,-150.4887,\n"
        "123,25-01-08 17:19:04,Spot,Transaction Spend,EUR,-8.9856,\n"
        "123,25-01-08 17:19:04,Spot,Transaction Fee,BNB,-0.000010,\n"
        "123,25-01-08 17:19:04,Spot,Transaction Spend,EUR,-680.659,\n"
        "123,25-01-08 17:19:04,Spot,Transaction Fee,BNB,-0.000755,\n"
        "123,25-01-08 17:19:04,Spot,Transaction Buy,XRP,4.0,\n"
        "123,25-01-08 17:19:04,Spot,Transaction Spend,EUR,-150.5088,\n"
        "123,25-01-08 17:19:04,Spot,Transaction Fee,BNB,-0.000010,\n"
        "123,25-01-08 17:19:04,Spot,Transaction Spend,EUR,-8.9848,\n"
        "123,25-01-08 17:19:04,Spot,Transaction Buy,XRP,67.0,\n"
        "123,25-01-08 17:19:04,Spot,Transaction Fee,BNB,-0.000167,\n"
    )
    c = ClasificadorBinanceTx(_csv_to_tmpfile(csv, tmp_path)).clasificar()

    assert len(c.compraventas) == 1, "Debe generar UNA sola COMPRA (todas las filas sumadas)"
    assert len(c.swaps) == 0
    cv = c.compraventas[0]
    assert cv.tipo       == "COMPRA"
    assert cv.activo     == "XRP"
    assert cv.contraparte == "EUR"
    assert cv.cantidad   == pytest.approx(445.0), f"XRP recibido esperado 445, obtenido {cv.cantidad}"
    assert cv.importe    == pytest.approx(999.6269, rel=1e-4), \
        f"EUR pagado esperado ~999.63, obtenido {cv.importe}"
    assert len(c.desconocidas) == 0


# ── Test 6: Small Assets Exchange BNB ─────────────────────────────────────────

def test_small_assets_exchange_bnb(tmp_path):
    """
    Small Assets Exchange BNB: filas negativas (crypto dado) y positivas (BNB recibido).
    Ambas deben clasificarse como MOVIMIENTO, no como rendimiento ni compraventa.
    No debe afectar al motor FIFO (no genera compraventas).
    """
    csv = HEADER + (
        "123,24-05-01 09:32:03,Spot,Small Assets Exchange BNB,FET,-0.035342,FET to BNB\n"
        "123,24-05-01 09:32:03,Spot,Small Assets Exchange BNB,PEPE,-3057.06,PEPE to BNB\n"
        "123,24-05-01 09:32:03,Spot,Small Assets Exchange BNB,BNB,0.000034,PEPE to BNB\n"
        "123,24-05-01 09:32:03,Spot,Small Assets Exchange BNB,BNB,0.000063,FET to BNB\n"
    )
    c = ClasificadorBinanceTx(_csv_to_tmpfile(csv, tmp_path)).clasificar()

    assert len(c.compraventas) == 0, "No debe generar compraventas (no afecta FIFO)"
    assert len(c.rendimientos) == 0, "No debe generar rendimientos (no es ingreso directo)"
    assert len(c.movimientos)  == 4, "Las 4 filas deben clasificarse como MOVIMIENTO"
    assert len(c.desconocidas) == 0

    # Verificar que los movimientos negativos (disposals) están registrados
    monedas_mov = {m.activo for m in c.movimientos}
    assert "FET"  in monedas_mov
    assert "PEPE" in monedas_mov
    assert "BNB"  in monedas_mov

    # Verificar signos: los negativos conservan su signo para trazabilidad
    cantidades = {m.activo: m.cantidad for m in c.movimientos if m.activo != "BNB"}
    assert cantidades["FET"]  < 0, "FET entregado debe tener Cambio negativo"
    assert cantidades["PEPE"] < 0, "PEPE entregado debe tener Cambio negativo"


# ── Test 7: No duplica operaciones ────────────────────────────────────────────

def test_sin_duplicados_transaction_buy_spend(tmp_path):
    """
    Dos grupos de Transaction Buy/Spend en segundos distintos no deben
    interferir entre sí ni generar operaciones duplicadas.
    """
    csv = HEADER + (
        # Grupo 1: USDC → XRP
        "123,24-12-11 22:51:06,Spot,Transaction Spend,USDC,-100.0,\n"
        "123,24-12-11 22:51:06,Spot,Transaction Buy,XRP,40.0,\n"
        # Grupo 2 (segundo distinto): EUR → XRP
        "123,25-01-08 17:19:04,Spot,Transaction Spend,EUR,-50.0,\n"
        "123,25-01-08 17:19:04,Spot,Transaction Buy,XRP,20.0,\n"
    )
    c = ClasificadorBinanceTx(_csv_to_tmpfile(csv, tmp_path)).clasificar()

    assert len(c.swaps)        == 1, "Un SWAP (USDC→XRP)"
    assert len(c.compraventas) == 1, "Una COMPRA (EUR→XRP)"
    assert c.swaps[0].activo_entregado   == "USDC"
    assert c.compraventas[0].activo      == "XRP"
    assert c.compraventas[0].contraparte == "EUR"
    assert len(c.desconocidas) == 0


# ── Tests de parsing de fechas (_parse_tiempo) ────────────────────────────────
# Verifican que ningún cambio de formato Binance rompa la importación y que
# el FIFO no se vea afectado (solo cambia la representación de la fecha).

def test_fecha_formato_antiguo_2digit_year_con_hora(tmp_path):
    """Formato histórico Binance: año 2 dígitos + hora — debe seguir funcionando."""
    csv = HEADER + "123,24-06-15 10:00:00,Spot,Commission Rebate,EUR,0.50,\n"
    c = ClasificadorBinanceTx(_csv_to_tmpfile(csv, tmp_path)).clasificar()
    assert len(c.rendimientos) == 1
    r = c.rendimientos[0]
    # Fecha parseada correctamente: 2024-06-15
    assert "2024" in r.fecha, f"Año esperado 2024 en fecha: {r.fecha}"
    assert "06" in r.fecha
    assert "15" in r.fecha


def test_fecha_formato_nuevo_4digit_year_con_hora(tmp_path):
    """Formato nuevo Binance: año 4 dígitos + hora — el bug real de producción."""
    csv = HEADER + "123,2025-12-31 14:30:00,Spot,Commission Rebate,EUR,1.00,\n"
    c = ClasificadorBinanceTx(_csv_to_tmpfile(csv, tmp_path)).clasificar()
    assert len(c.rendimientos) == 1
    r = c.rendimientos[0]
    assert "2025" in r.fecha
    assert "12" in r.fecha
    assert "31" in r.fecha


def test_fecha_formato_nuevo_4digit_year_sin_hora(tmp_path):
    """Formato sin hora: 2025-12-31 — variante del bug de producción."""
    csv = HEADER + "123,2025-12-31,Spot,Commission Rebate,EUR,2.00,\n"
    c = ClasificadorBinanceTx(_csv_to_tmpfile(csv, tmp_path)).clasificar()
    assert len(c.rendimientos) == 1
    r = c.rendimientos[0]
    assert "2025" in r.fecha
    assert "12" in r.fecha
    assert "31" in r.fecha


def test_fecha_formato_mixto_en_misma_columna(tmp_path):
    """CSV con filas en formato antiguo y nuevo mezcladas — debe cargarse sin error."""
    csv = (
        HEADER
        + "123,24-06-15 10:00:00,Spot,Commission Rebate,EUR,0.50,\n"
        + "123,2025-12-31 14:30:00,Spot,Commission Rebate,EUR,1.00,\n"
    )
    # No debe lanzar excepción — ambas filas se procesan
    c = ClasificadorBinanceTx(_csv_to_tmpfile(csv, tmp_path)).clasificar()
    assert len(c.rendimientos) == 2


def test_fecha_formato_desconocido_loguea_warning(tmp_path, caplog):
    """
    Formato no listado en _TIEMPO_FORMATOS: el parser flexible lo acepta
    (no debe explotar con datos razonables) pero DEBE registrar un WARNING
    explícito para detectar cambios futuros de exportación del exchange.
    """
    import logging
    csv = HEADER + "123,31/12/2025-10:00,Spot,Commission Rebate,EUR,1.00,\n"
    with caplog.at_level(logging.WARNING, logger="clasificador_binance_tx"):
        c = ClasificadorBinanceTx(_csv_to_tmpfile(csv, tmp_path)).clasificar()
    # El WARNING debe aparecer con texto orientativo
    assert any("Binance TX" in m for m in caplog.messages), (
        "Se esperaba un WARNING sobre formato de fecha desconocido"
    )
    assert any("_TIEMPO_FORMATOS" in m for m in caplog.messages)
    # A pesar del formato inusual, la fila se clasifica (no se pierde)
    assert len(c.rendimientos) == 1


def test_fecha_completamente_rota_lanza_error(tmp_path):
    """Cadena que no es una fecha válida bajo ningún criterio debe lanzar excepción."""
    csv = HEADER + "123,no-es-una-fecha,Spot,Commission Rebate,EUR,1.00,\n"
    with pytest.raises(Exception):
        ClasificadorBinanceTx(_csv_to_tmpfile(csv, tmp_path)).clasificar()


# ── Tests NaN en columna "Operación" (bug producción 2026-06-05) ──────────────

def test_operacion_vacia_no_crashea(tmp_path):
    """
    CSV con una fila donde "Operación" está vacía.
    Pandas lee la celda como float NaN — el clasificador no debe lanzar TypeError.
    Regresión del error: 'sequence item 0: expected str instance, float found'
    """
    csv = HEADER + "123,2026-06-05 07:00:00,Spot,,BTC,0.001,\n"
    # No debe lanzar ninguna excepción
    c = ClasificadorBinanceTx(_csv_to_tmpfile(csv, tmp_path)).clasificar()
    assert c is not None


def test_operacion_vacia_queda_como_desconocida_o_advertencia(tmp_path):
    """
    Una fila con "Operación" vacía debe quedar en desconocidas o generar
    una advertencia — nunca perderse en silencio ni crashear.
    """
    csv = HEADER + "123,2026-06-05 07:00:00,Spot,,BTC,0.001,\n"
    c = ClasificadorBinanceTx(_csv_to_tmpfile(csv, tmp_path)).clasificar()

    tiene_rastro = len(c.desconocidas) > 0 or len(c.advertencias) > 0
    assert tiene_rastro, (
        "Una fila con Operación vacía debe quedar en desconocidas o generar advertencia"
    )


def test_operacion_vacia_no_produce_texto_nan(tmp_path):
    """
    El informe/advertencia no debe contener el texto literal 'nan' cuando
    la columna "Operación" es NaN — ese texto confundiría al usuario.
    """
    csv = HEADER + "123,2026-06-05 07:00:00,Spot,,BTC,0.001,\n"
    c = ClasificadorBinanceTx(_csv_to_tmpfile(csv, tmp_path)).clasificar()

    for adv in c.advertencias:
        assert "nan" not in adv.lower(), f"Advertencia contiene 'nan': {adv!r}"

    for op in c.desconocidas:
        subtipo_str = str(op.subtipo) if op.subtipo is not None else ""
        assert subtipo_str.lower() != "nan", (
            f"subtipo de desconocida es 'nan' (literal): {op!r}"
        )


def test_advertencia_tipos_desconocidos_legible_con_nan(tmp_path):
    """
    Mezcla de fila con Operación vacía y otra con tipo desconocido real.
    La advertencia de resumen debe ser legible y no incluir 'nan'.
    """
    csv = (
        HEADER
        + "123,2026-06-05 07:00:00,Spot,,BTC,0.001,\n"
        + "123,2026-06-05 08:00:00,Spot,Tipo Inventado XYZ,ETH,0.5,\n"
    )
    c = ClasificadorBinanceTx(_csv_to_tmpfile(csv, tmp_path)).clasificar()

    assert len(c.advertencias) > 0, "Debe haber al menos una advertencia"
    adv_texto = " ".join(c.advertencias)
    assert "nan" not in adv_texto.lower(), (
        f"La advertencia contiene 'nan': {adv_texto!r}"
    )
    # El tipo real sí debe aparecer
    assert "Tipo Inventado XYZ" in adv_texto, (
        f"El tipo desconocido real no aparece en la advertencia: {adv_texto!r}"
    )


def test_pipeline_completo_no_lanza_typeerror_con_operacion_nan(tmp_path):
    """
    Pipeline completo (clasificar + motor FIFO) con CSV que tiene una fila
    de Operación vacía. No debe lanzar TypeError en ningún punto de la cadena.
    Regresión directa del bug de producción 2026-06-05 (fingerprint 1ab51930).
    """
    from motor_fifo import MotorFIFO

    csv = (
        HEADER
        + "123,2026-06-05 06:00:00,Spot,Transaction Spend,EUR,-100.0,\n"
        + "123,2026-06-05 06:00:00,Spot,Transaction Buy,BTC,0.001,\n"
        + "123,2026-06-05 07:00:00,Spot,,BTC,0.001,\n"  # fila con Operación vacía
    )
    try:
        c = ClasificadorBinanceTx(_csv_to_tmpfile(csv, tmp_path)).clasificar()
        motor = MotorFIFO()
        for op in c.compraventas:
            motor.registrar_compra(
                fecha=op.fecha, activo=op.activo,
                cantidad=op.cantidad, importe=op.importe,
                contraparte=op.contraparte,
                fee_activo=None, fee_cantidad=0,
            )
        for op in c.swaps:
            motor.registrar_swap(
                fecha=op.fecha,
                activo_entregado=op.activo_entregado, cantidad_entregada=op.cantidad_entregada,
                activo_recibido=op.activo_recibido,   cantidad_recibida=op.cantidad_recibida,
            )
    except TypeError as e:
        pytest.fail(f"TypeError inesperado en pipeline completo: {e}")


def test_fecha_parse_tiempo_directo_formatos():
    """Prueba unitaria directa de _parse_tiempo para los 4 formatos soportados."""
    casos = [
        ("24-06-15 10:00:00", 2024, 6, 15),   # %y-%m-%d %H:%M:%S — histórico
        ("2025-12-31 14:30:00", 2025, 12, 31), # %Y-%m-%d %H:%M:%S — nuevo con hora
        ("2025-12-31", 2025, 12, 31),           # %Y-%m-%d — nuevo sin hora
        ("24-06-15", 2024, 6, 15),              # %y-%m-%d — sin hora, año corto
    ]
    for valor, año_esp, mes_esp, dia_esp in casos:
        serie = pd.Series([valor])
        resultado = _parse_tiempo(serie)
        ts = resultado.iloc[0]
        assert ts.year  == año_esp,  f"Año incorrecto para {valor!r}: {ts.year} != {año_esp}"
        assert ts.month == mes_esp,  f"Mes incorrecto para {valor!r}: {ts.month} != {mes_esp}"
        assert ts.day   == dia_esp,  f"Día incorrecto para {valor!r}: {ts.day} != {dia_esp}"
