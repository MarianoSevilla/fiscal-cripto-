"""
Tests para ClasificadorKuCoin (flujo multiarchivo).

Las fixtures de fiscal_app_export/tests/fixtures/kucoin/ son los CSV REALES de
KuCoin (UID 64476041, ejercicio 2025). Los tests de valores específicos contra
fixtures asertan el ground truth real verificado a mano. Los casos límite usan
CSV sintéticos inline para no depender de datos concretos.

Cubre:
  · Detección de tipo por cabecera (ledger / fiat_orders / deposito_cripto / desconocido)
  · Fichero vacío "No matching records found." → reconocido válido vacío, sin error
  · Ground truth real: 22 compraventas, dedup fiat, dust multiactivo
  · Reconstrucción Spot por consolidación (varias filas mismo segundo)
  · Fiat Transactions con patas a 1 segundo → clustering por ventana (regresión)
  · Spot ambiguo (varias monedas) → advertencia, no inventa
  · Convert Dust 1 activo → swap; multiactivo → advertencia
  · Deduplicación fiat contra Cuenta de financiación
  · Compatibilidad con MotorFIFO
"""

import os
import tempfile
import pytest

from fiscal_app_export.clasificador_kucoin import (
    ClasificadorKuCoin,
    KucoinUserError,
    _detectar_tipo,
    _norm_header,
)

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "kucoin")

F_VACIO    = os.path.join(FIXTURES, "Historial de depósitos_retiradas_Historial de depósitos.csv")
F_FINANC   = os.path.join(FIXTURES, "Historial de la cuenta_Cuenta de financiación.csv")
F_TRADING  = os.path.join(FIXTURES, "Historial de la cuenta_Cuenta de trading.csv")
F_FIAT_ORD = os.path.join(FIXTURES, "Órdenes fiat_Depósitos fiat.csv")

LEDGER_HEADER = "UID,Account Type,Currency,Side,Amount,Fee,Time(UTC+02:00),Remark,Type"


def _csv_tmp(contenido: str) -> str:
    fd, path = tempfile.mkstemp(suffix=".csv")
    os.close(fd)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        f.write(contenido)
    return path


def _clasificar(*paths):
    return ClasificadorKuCoin(list(paths)).clasificar()


# ── DETECCIÓN DE FORMATO ───────────────────────────────────────────────────────

class TestDeteccion:
    def test_norm_header_quita_offset(self):
        assert _norm_header("Time(UTC+02:00)") == "time"
        assert _norm_header("Time(UTC-05:00)") == "time"
        assert _norm_header("Currency (Fiat)") == "currency (fiat)"

    def test_detecta_ledger(self):
        assert _detectar_tipo(LEDGER_HEADER.split(",")) == "ledger"

    def test_detecta_fiat_orders(self):
        h = "Order ID,Currency (Fiat),Fiat Amount,Fee,Deposit Method,Status,Time(UTC+02:00)"
        assert _detectar_tipo(h.split(",")) == "fiat_orders"

    def test_detecta_deposito_cripto(self):
        h = "UID,Account Type,Time(UTC+02:00),Coin,Amount,Fee,Hash,Deposit Address,Transfer Network,Status,Remarks"
        assert _detectar_tipo(h.split(",")) == "deposito_cripto"

    def test_desconocido(self):
        assert _detectar_tipo(["foo", "bar", "baz"]) == "desconocido"


# ── FICHEROS VACÍOS ────────────────────────────────────────────────────────────

class TestVacios:
    def test_no_matching_records_es_valido_vacio(self):
        c = _clasificar(F_VACIO)
        assert c.resumen_archivos["deposito_cripto"]["detectado"] is True
        assert c.resumen_archivos["deposito_cripto"]["vacio"] is True
        assert c.movimientos == []
        assert c.compraventas == []

    def test_solo_vacio_no_lanza_error(self):
        c = _clasificar(F_VACIO)
        assert isinstance(c, ClasificadorKuCoin)

    def test_ningun_fichero_reconocido_lanza_user_error(self):
        p = _csv_tmp("foo,bar,baz\n1,2,3\n")
        try:
            with pytest.raises(KucoinUserError) as exc:
                _clasificar(p)
            assert exc.value.code == "wrong_file"
            assert exc.value.category == "user_error"
        finally:
            os.unlink(p)

    def test_sin_ficheros_lanza_error(self):
        with pytest.raises(KucoinUserError):
            ClasificadorKuCoin([]).clasificar()


# ── GROUND TRUTH CON LOS CSV REALES ────────────────────────────────────────────

class TestDatosReales:
    """Asertos sobre los 4 CSV reales de KuCoin (UID 64476041, 2025)."""

    def _full(self):
        return _clasificar(F_TRADING, F_FINANC, F_FIAT_ORD, F_VACIO)

    def test_totales(self):
        c = self._full()
        assert len(c.compraventas) == 22
        assert len(c.swaps) == 0          # el único dust es multiactivo → advertencia
        assert len(c.desconocidas) == 0   # todo clasificado
        # todas son COMPRA (el usuario sólo acumuló, nunca vendió a EUR)
        assert all(o.tipo == "COMPRA" for o in c.compraventas)

    def test_resumen_archivos_real(self):
        c = self._full()
        r = c.resumen_archivos
        assert r["trading"]["registros"] == 136
        assert r["financiacion"]["registros"] == 28
        assert r["fiat_orders"]["registros"] == 6
        assert r["deposito_cripto"]["vacio"] is True
        assert r["no_reconocidos"] == []

    def test_spot_xrp_primera_compra(self):
        c = self._full()
        xrp = [o for o in c.compraventas if o.activo == "XRP"
               and o.fecha.startswith("2025-10-12")]
        assert len(xrp) == 1
        op = xrp[0]
        assert round(op.cantidad, 4) == 125.2667
        assert round(op.importe, 6) == 300.299967
        assert op.contraparte == "USDT"

    def test_spot_consolidacion_xlm(self):
        # 2 XLM Deposits + 2 USDT Withdrawals mismo segundo → una COMPRA agregada
        c = self._full()
        xlm = [o for o in c.compraventas if o.activo == "XLM"
               and o.fecha.startswith("2025-10-12")]
        assert len(xlm) == 1
        assert round(xlm[0].cantidad, 2) == 917.15        # 338.61 + 578.54
        assert round(xlm[0].importe, 2) == 300.30         # 189.43 + 110.87

    def test_fiat_transactions_skew_1seg(self):
        # CASO CRÍTICO: EUR Withdrawal @09:55:40 + USDT Deposit @09:55:41
        # (1 segundo de diferencia) → debe reconstruirse como UNA compra de USDT.
        c = self._full()
        compra_usdt_eur = [o for o in c.compraventas
                           if o.activo == "USDT" and o.contraparte == "EUR"
                           and o.fecha.startswith("2025-10-12")]
        assert len(compra_usdt_eur) == 1
        op = compra_usdt_eur[0]
        assert round(op.cantidad, 6) == 1013.642815
        assert round(op.importe, 2) == 898.0

    def test_dust_multiactivo_advertencia(self):
        c = self._full()
        assert c.swaps == []
        assert any("varios activos" in a.lower() for a in c.advertencias)

    def test_dedup_fiat_todas_las_ordenes(self):
        # Las 6 órdenes fiat coinciden con 6 Fiat Deposit del ledger (importe ~1%,
        # mismo día) → ninguna se añade como complemento.
        c = self._full()
        fiat_orders = [m for m in c.movimientos if m.subtipo == "Fiat Order"]
        assert fiat_orders == []
        fiat_deposits = [m for m in c.movimientos if m.subtipo == "Fiat Deposit"]
        assert len(fiat_deposits) == 6

    def test_anos_detectados(self):
        c = self._full()
        años = set()
        for grupo in (c.compraventas, c.swaps, c.movimientos):
            for op in grupo:
                años.add(int(str(op.fecha)[:4]))
        assert años == {2025}


# ── CLUSTERING POR VENTANA (regresión del skew de 1 segundo) ──────────────────

class TestClusteringTemporal:
    def test_patas_a_1_segundo_se_agrupan(self):
        contenido = (
            LEDGER_HEADER + "\n"
            "1,m,EUR,Withdrawal,100,0,2025-05-01 10:00:00,,Fiat Transactions\n"
            "1,m,USDT,Deposit,110,0,2025-05-01 10:00:01,,Fiat Transactions\n"
        )
        p = _csv_tmp(contenido)
        try:
            c = _clasificar(p)
            assert len(c.compraventas) == 1
            op = c.compraventas[0]
            assert op.activo == "USDT" and op.contraparte == "EUR"
            assert op.importe == 100.0 and op.cantidad == 110.0
        finally:
            os.unlink(p)

    def test_operaciones_separadas_no_se_fusionan(self):
        # Dos compras distintas separadas por minutos → 2 operaciones, no 1
        contenido = (
            LEDGER_HEADER + "\n"
            "1,m,XRP,Deposit,10,0,2025-05-01 10:00:00,,Spot\n"
            "1,m,USDT,Withdrawal,20,0,2025-05-01 10:00:00,,Spot\n"
            "1,m,XLM,Deposit,30,0,2025-05-01 10:05:00,,Spot\n"
            "1,m,USDT,Withdrawal,15,0,2025-05-01 10:05:00,,Spot\n"
        )
        p = _csv_tmp(contenido)
        try:
            c = _clasificar(p)
            assert len(c.compraventas) == 2
            activos = {o.activo for o in c.compraventas}
            assert activos == {"XRP", "XLM"}
        finally:
            os.unlink(p)


# ── CASOS AMBIGUOS (no inventar) ───────────────────────────────────────────────

class TestAmbiguos:
    def test_spot_varias_monedas_genera_advertencia(self):
        contenido = (
            LEDGER_HEADER + "\n"
            "1,m,XRP,Deposit,10,0,2025-06-01 10:00:00,,Spot\n"
            "1,m,ADA,Deposit,20,0,2025-06-01 10:00:00,,Spot\n"
            "1,m,USDT,Withdrawal,50,0,2025-06-01 10:00:00,,Spot\n"
        )
        p = _csv_tmp(contenido)
        try:
            c = _clasificar(p)
            assert c.compraventas == []
            assert any("no se pudo reconstruir" in a.lower() for a in c.advertencias)
            assert len(c.desconocidas) == 3
        finally:
            os.unlink(p)

    def test_convert_dust_un_activo_es_swap(self):
        contenido = (
            LEDGER_HEADER + "\n"
            "1,m,DOGE,Withdrawal,15.5,0,2025-06-02 03:00:00,,Convert Dust to KCS\n"
            "1,m,KCS,Deposit,0.12,0,2025-06-02 03:00:00,,Convert Dust to KCS\n"
        )
        p = _csv_tmp(contenido)
        try:
            c = _clasificar(p)
            assert len(c.swaps) == 1
            s = c.swaps[0]
            assert s.activo_entregado == "DOGE" and s.activo_recibido == "KCS"
            assert s.cantidad_recibida == 0.12
        finally:
            os.unlink(p)

    def test_convert_dust_multiactivo_genera_advertencia(self):
        contenido = (
            LEDGER_HEADER + "\n"
            "1,m,DOGE,Withdrawal,15,0,2025-06-02 03:00:00,,Convert Dust to KCS\n"
            "1,m,SHIB,Withdrawal,1000000,0,2025-06-02 03:00:00,,Convert Dust to KCS\n"
            "1,m,KCS,Deposit,0.2,0,2025-06-02 03:00:00,,Convert Dust to KCS\n"
        )
        p = _csv_tmp(contenido)
        try:
            c = _clasificar(p)
            assert c.swaps == []
            assert any("varios activos" in a.lower() for a in c.advertencias)
        finally:
            os.unlink(p)

    def test_dust_sin_kcs_genera_advertencia(self):
        contenido = (
            LEDGER_HEADER + "\n"
            "1,m,DOGE,Withdrawal,15,0,2025-06-03 03:00:00,,Convert Dust to KCS\n"
            "1,m,BTC,Deposit,0.0001,0,2025-06-03 03:00:00,,Convert Dust to KCS\n"
        )
        p = _csv_tmp(contenido)
        try:
            c = _clasificar(p)
            assert c.swaps == []
            assert any("kcs" in a.lower() for a in c.advertencias)
        finally:
            os.unlink(p)


# ── DEDUPLICACIÓN FIAT ─────────────────────────────────────────────────────────

class TestDedupFiat:
    def test_fiat_orders_solo_sin_financiacion(self):
        # Sin Cuenta de financiación, las órdenes fiat se cuentan como complemento.
        c = _clasificar(F_FIAT_ORD)
        fiat_orders = [m for m in c.movimientos if m.subtipo == "Fiat Order"]
        assert len(fiat_orders) == 6

    def test_dedup_por_dia_e_importe(self):
        # Order EUR 100 (gross) ↔ Fiat Deposit EUR 99 (net) mismo día → dedup.
        # Order EUR 50 sin equivalente → complemento.
        ledger = (
            LEDGER_HEADER + "\n"
            "1,m,EUR,Deposit,99,1,2025-07-01 10:00:00,ee,Fiat Deposit\n"
        )
        orders = (
            "Order ID,Currency (Fiat),Fiat Amount,Fee,Deposit Method,Status,Time(UTC+02:00)\n"
            "o1,EUR,100,1,ee,SUCCEEDED,2025-07-01 09:59:58\n"
            "o2,EUR,50,1,ee,SUCCEEDED,2025-08-15 12:00:00\n"
        )
        pl, po = _csv_tmp(ledger), _csv_tmp(orders)
        try:
            c = _clasificar(pl, po)
            fiat_orders = [m for m in c.movimientos if m.subtipo == "Fiat Order"]
            assert len(fiat_orders) == 1
            assert fiat_orders[0].cantidad == 50.0
        finally:
            os.unlink(pl); os.unlink(po)


# ── COMPATIBILIDAD CON MOTORFIFO ───────────────────────────────────────────────

class TestMotorFIFO:
    def test_pipeline_motor_real(self):
        from fiscal_app_export.motor_fifo import MotorFIFO
        c = _clasificar(F_TRADING, F_FINANC, F_FIAT_ORD, F_VACIO)
        motor = MotorFIFO()
        ops = [("cv", o.fecha, o) for o in c.compraventas]
        ops += [("swap", o.fecha, o) for o in c.swaps]
        ops.sort(key=lambda x: x[1])
        for tipo, _f, op in ops:
            if tipo == "cv":
                fn = motor.registrar_compra if op.tipo == "COMPRA" else motor.registrar_venta
                fn(fecha=op.fecha, activo=op.activo, cantidad=op.cantidad,
                   importe=op.importe, contraparte=op.contraparte,
                   fee_activo=op.fee_activo, fee_cantidad=op.fee_cantidad)
            else:
                motor.registrar_swap(
                    fecha=op.fecha, activo_entregado=op.activo_entregado,
                    cantidad_entregada=op.cantidad_entregada,
                    activo_recibido=op.activo_recibido,
                    cantidad_recibida=op.cantidad_recibida, nota=op.nota)
        resumen = motor.resumen_fiscal()
        assert "resultado_neto" in resumen
        # El usuario sólo acumuló: posición FIFO no vacía, sin ventas realizadas.
        assert len(motor.posicion_actual()) > 0
        assert len(motor.resultados) == 0
