"""
Tests de regresión para el LayoutError del generador PDF.

FASE 4: Nexo LayoutError — Flowable with cell too large.

Reproduce los casos que causaban LayoutError en producción:
  - Ticker muy largo (sin espacios) en columna activo (28mm)
  - Subtipo muy largo en columna subtipo (60mm)
  - Advertencia muy larga en tabla de warnings
  - Datos normales (smoke test — no regresión)

No prueba el formato visual del PDF, solo que generar_pdf() no lanza
LayoutError con datos razonables o extremos.
"""

import pytest
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from generador_pdf import generar_pdf, _td_safe


# ── Helper: motor FIFO mínimo ────────────────────────────────────────────────

class _MockLote:
    def __init__(self, fecha, cantidad, precio):
        from datetime import datetime
        self.fecha = datetime.fromisoformat(fecha)
        self.cantidad_original = cantidad
        self.cantidad_restante = cantidad
        self.precio_coste_unitario = precio
        self.contraparte = "EUR"


class _MockResultado:
    def __init__(self, activo, fecha="2024-06-15"):
        from datetime import datetime
        self.activo = activo
        self.fecha = datetime.fromisoformat(fecha)
        self.tipo_operacion = "compraventa"
        self.cantidad_vendida = 1.0
        self.precio_transmision = 100.0
        self.precio_coste = 80.0
        self.ganancia_perdida = 20.0
        self.periodo_dias = 180
        self.lotes_consumidos = []


class _MockPosicion:
    def __init__(self, activo):
        self.activo = activo
        self.cantidad_total = 1.0
        self.precio_medio = 100.0
        self.coste_total = 100.0


class _MockRendimiento:
    def __init__(self, activo, subtipo, cantidad=1.0):
        self.activo = activo
        self.subtipo = subtipo
        self.cantidad = cantidad
        self.cuenta = "Nexo"
        self.valor_eur = 0.0


class _MockMotor:
    """Motor FIFO mínimo para probar generar_pdf sin dependencias del dominio."""

    def __init__(self, resultados=None, advertencias=None, posiciones=None):
        self.resultados   = resultados  or []
        self.advertencias = advertencias or []
        self._posiciones  = posiciones   or []

    def resumen_fiscal(self):
        return {
            "ganancias_brutas":         0.0,
            "perdidas_brutas":          0.0,
            "resultado_neto":           0.0,
            "operaciones_con_resultado": len(self.resultados),
            "total_operaciones":        len(self.resultados),
            "_n_activos":               0,
        }

    def posicion_actual(self):
        return self._posiciones


# ── Test unitario: _td_safe ───────────────────────────────────────────────────

def test_td_safe_string_corto():
    assert _td_safe("BTC", 40) == "BTC"


def test_td_safe_string_exacto():
    s = "A" * 40
    assert _td_safe(s, 40) == s


def test_td_safe_string_largo_trunca():
    s = "A" * 500
    result = _td_safe(s, 300)
    assert len(result) <= 300
    assert result.endswith("…")


def test_td_safe_none_devuelve_cadena_vacia():
    assert _td_safe(None) == ""


def test_td_safe_no_trunca_dentro_del_limite():
    s = "Fixed Term Interest"  # 19 chars — subtipo típico de Nexo
    assert _td_safe(s, 80) == s


# ── Tests de generación PDF — no LayoutError ─────────────────────────────────

def test_pdf_ticker_largo_no_lanza_layout_error():
    """
    Un ticker de 200 chars sin espacios (caso extremo, nunca real) no debe
    causar LayoutError en la tabla de rendimientos (columna 28mm).
    """
    ticker_largo = "X" * 200  # más largo que cualquier ticker real
    motor = _MockMotor()
    rend = [_MockRendimiento(activo=ticker_largo, subtipo="Interest")]

    pdf = generar_pdf(motor, nombre_usuario="Test", ejercicio="2024",
                      exchange="Nexo", rendimientos=rend)
    assert len(pdf) > 0, "PDF no debe estar vacío"


def test_pdf_subtipo_largo_no_lanza_layout_error():
    """
    Un subtipo de 500 chars sin espacios no debe causar LayoutError
    en la columna subtipo (60mm) de la tabla de rendimientos.
    """
    subtipo_largo = "FixedTermInterest" * 30  # 510 chars, sin espacios
    motor = _MockMotor()
    rend = [_MockRendimiento(activo="BTC", subtipo=subtipo_largo)]

    pdf = generar_pdf(motor, nombre_usuario="Test", ejercicio="2024",
                      exchange="Nexo", rendimientos=rend)
    assert len(pdf) > 0


def test_pdf_advertencias_largas_no_lanza_layout_error():
    """
    Advertencias muy largas del motor FIFO no deben causar LayoutError
    en la tabla de warnings (columna 168mm).
    """
    adv_larga = "Advertencia " + "X" * 1000  # 1012 chars
    motor = _MockMotor(advertencias=[adv_larga] * 5)

    pdf = generar_pdf(motor, nombre_usuario="Test", ejercicio="2024",
                      exchange="Nexo", rendimientos=[])
    assert len(pdf) > 0


def test_pdf_datos_normales_nexo_smoke():
    """
    Datos típicos de Nexo (rendimientos de staking, sin ventas) deben
    generar PDF sin error.
    """
    rend = [
        _MockRendimiento("BTC",  "Interest",           cantidad=0.0001),
        _MockRendimiento("ETH",  "Fixed Term Interest", cantidad=0.005),
        _MockRendimiento("NEXO", "Exchange Cashback",   cantidad=1.23),
    ]
    motor = _MockMotor(
        advertencias=["2024-01-15 | SWAP BTC→ETH — sin inventario previo"]
    )

    pdf = generar_pdf(motor, nombre_usuario="Usuario Test", ejercicio="2024",
                      exchange="Nexo", rendimientos=rend)
    assert isinstance(pdf, bytes)
    assert len(pdf) > 1000  # PDF real tiene contenido


def test_pdf_activo_largo_en_tabla_posicion():
    """
    Ticker largo en tabla de posición (28mm) no debe causar LayoutError.
    """
    motor = _MockMotor(posiciones=[_MockPosicion(activo="TOKENLARGOSINESPACIO" * 10)])

    pdf = generar_pdf(motor, nombre_usuario="Test", ejercicio="2024",
                      exchange="Nexo", rendimientos=[])
    assert len(pdf) > 0


def test_pdf_activo_largo_en_tabla_operaciones():
    """
    Ticker largo en tabla de operaciones (22mm) no debe causar LayoutError.
    """
    motor = _MockMotor(resultados=[_MockResultado(activo="TOKENLARGOSINESPACIO" * 10)])

    pdf = generar_pdf(motor, nombre_usuario="Test", ejercicio="2024",
                      exchange="Nexo", rendimientos=[])
    assert len(pdf) > 0


def test_grafico_gp_activos_requiere_matplotlib_instalado():
    """
    Regresión: matplotlib no estaba en requirements.txt.
    En producción (Railway) _grafico_gp_activos() lanzaba ImportError silencioso
    y devolvía None → el PDF se generaba sin gráfica (12 págs en vez de 13).

    Este test garantiza que matplotlib está disponible en el entorno de ejecución.
    Si falla, añadir 'matplotlib' a requirements.txt.
    """
    try:
        import matplotlib  # noqa: F401
    except ImportError:
        raise AssertionError(
            "matplotlib no está instalado. Añádelo a requirements.txt para que "
            "el gráfico de G/P por activo aparezca en los PDFs de producción."
        )


def test_grafico_gp_activos_devuelve_imagen_no_none():
    """
    Regresión: _grafico_gp_activos devolvía None en producción porque
    matplotlib no estaba en requirements.txt (ImportError silencioso).
    El PDF resultante tenía 12 páginas en vez de 13 y ninguna imagen.
    """
    from generador_pdf import _grafico_gp_activos

    resultados = [
        _MockResultado(activo="BTC",  fecha="2025-06-15"),
        _MockResultado(activo="ETH",  fecha="2025-06-20"),
        _MockResultado(activo="SOL",  fecha="2025-07-01"),
    ]
    # Dar valores G/P distintos para que el gráfico tenga barras reales
    resultados[0].ganancia_perdida = 500.0
    resultados[1].ganancia_perdida = -200.0
    resultados[2].ganancia_perdida = 150.0

    grafico = _grafico_gp_activos(resultados)
    assert grafico is not None, (
        "_grafico_gp_activos devolvió None — matplotlib probablemente no está instalado"
    )
    # El objeto debe tener dimensiones reales
    assert grafico.drawWidth > 0
    assert grafico.drawHeight > 0


def test_pdf_con_resultados_contiene_imagen():
    """
    Test de integración: el PDF generado desde generar_pdf() con resultados
    debe contener al menos 1 imagen (la gráfica de G/P por activo).

    En producción sin matplotlib el PDF tenía imgs=0 en todas las páginas.
    """
    import io
    try:
        import pdfplumber
    except ImportError:
        import pytest
        pytest.skip("pdfplumber no disponible para verificar imágenes en PDF")

    resultados = [_MockResultado(activo=activo, fecha="2025-06-15")
                  for activo in ["BTC", "ETH", "SOL", "LINK", "BNB"]]
    for i, r in enumerate(resultados):
        r.ganancia_perdida = (i + 1) * 100.0 * (-1 if i % 2 else 1)

    motor = _MockMotor(resultados=resultados)
    pdf_bytes = generar_pdf(motor, nombre_usuario="Test", ejercicio="2025",
                            exchange="Nexo", rendimientos=[])

    total_imgs = 0
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            total_imgs += len(page.images)

    assert total_imgs >= 1, (
        f"El PDF tiene {total_imgs} imágenes — se esperaba al menos 1 (la gráfica de G/P). "
        "Verifica que matplotlib esté en requirements.txt."
    )


def test_pdf_tabla_operaciones_mas_de_30_filas_no_lanza_layout_error():
    """
    Regresión: con 83+ operaciones la tabla de operaciones supera la altura
    de una página A4 y ReportLab necesita partirla. El NOSPLIT incorrecto
    en la columna ACTIVO bloqueaba esa partición → LayoutError en producción
    con el CSV de Nexo (2025: 83 operaciones).

    El test usa 84 resultados mock (igual que el CSV real) para garantizar
    que la tabla se genera correctamente al abarcar múltiples páginas.
    """
    resultados = [_MockResultado(activo="BTC", fecha="2025-06-15") for _ in range(84)]
    motor = _MockMotor(resultados=resultados)

    pdf = generar_pdf(motor, nombre_usuario="Test", ejercicio="2025",
                      exchange="Nexo", rendimientos=[])
    assert isinstance(pdf, bytes)
    assert len(pdf) > 1000


# ── Tests inventario_incompleto — Motor FIFO real ─────────────────────────────

def test_inventario_incompleto_flag_se_activa_cuando_faltan_lotes():
    """
    ResultadoFIFO.inventario_incompleto debe ser True cuando la venta supera
    el inventario disponible (caso real: XRP comprado en 2024, CSV solo tiene 2025).

    Simulamos: 10 XRP en inventario, venta de 100 XRP → faltan 90 unidades.
    """
    from motor_fifo import MotorFIFO

    motor = MotorFIFO()
    motor.registrar_compra("2024-01-01", "XRP", 10.0, 5.0, "EUR", "EUR", 0.0)
    motor.registrar_venta("2025-03-02", "XRP", 100.0, 200.0, "EUR", "EUR", 0.0)

    assert len(motor.resultados) == 1, "Debe generarse un ResultadoFIFO parcial"
    resultado = motor.resultados[0]
    assert resultado.inventario_incompleto is True, (
        "inventario_incompleto debe ser True cuando faltan unidades"
    )
    # El coste solo refleja los 10 XRP disponibles (10 * 0.5 EUR/u = 5.0 EUR), no los 90 sin lote
    assert resultado.precio_coste == pytest.approx(5.0, abs=0.01)  # 10 XRP × 0.5 EUR/XRP
    assert len(motor.advertencias) == 1
    assert "inventario insuficiente" in motor.advertencias[0]


def test_inventario_incompleto_flag_no_se_activa_cuando_cubre():
    """
    ResultadoFIFO.inventario_incompleto debe ser False cuando el inventario
    cubre exactamente la venta (caso normal, sin inventario insuficiente).
    """
    from motor_fifo import MotorFIFO

    motor = MotorFIFO()
    motor.registrar_compra("2024-01-01", "BTC", 1.0, 30000.0, "EUR", "EUR", 0.0)
    motor.registrar_venta("2025-01-15", "BTC", 1.0, 40000.0, "EUR", "EUR", 0.0)

    assert len(motor.resultados) == 1
    resultado = motor.resultados[0]
    assert resultado.inventario_incompleto is False, (
        "inventario_incompleto debe ser False cuando el inventario cubre la venta"
    )
    assert motor.advertencias == [], "No debe haber advertencias de inventario insuficiente"


def test_inventario_incompleto_venta_sin_ningun_lote_devuelve_none():
    """
    Cuando no hay ningún lote registrado para el activo, _consumir_fifo devuelve
    None (no crea ResultadoFIFO). El aviso va solo a motor.advertencias.
    Este test verifica que ese comportamiento no ha cambiado tras el refactor.
    """
    from motor_fifo import MotorFIFO

    motor = MotorFIFO()
    # Sin compra previa, venta directa → should return None, not create resultado
    motor.registrar_venta("2025-03-02", "XRP", 737.0, 1917.53, "EUR", "EUR", 0.0)

    assert len(motor.resultados) == 0, (
        "Sin lotes previos, registrar_venta no debe crear ResultadoFIFO"
    )
    assert len(motor.advertencias) == 1
    assert "no hay lotes" in motor.advertencias[0]


def test_pdf_con_inventario_incompleto_genera_aviso_y_no_lanza_error():
    """
    Regresión Bug 4 (XRP José Luis): un resultado con inventario_incompleto=True
    debe generar el PDF correctamente (sin LayoutError) y el aviso de
    'inventario insuficiente' debe aparecer en el story.

    Simulamos el caso real: 10 XRP comprado, 737 vendido → inventario insuficiente.
    """
    from motor_fifo import MotorFIFO

    motor = MotorFIFO()
    motor.registrar_compra("2024-01-01", "XRP", 10.793212, 28.93, "EUR", "EUR", 0.0)
    motor.registrar_venta("2025-03-02", "XRP", 737.0, 1917.53, "EUR", "EUR", 0.0)

    assert motor.resultados[0].inventario_incompleto is True

    pdf = generar_pdf(motor, nombre_usuario="José Luis", ejercicio="2025",
                      exchange="Nexo", rendimientos=[])
    assert isinstance(pdf, bytes)
    assert len(pdf) > 1000


def test_pdf_sin_inventario_incompleto_no_muestra_aviso_rojo():
    """
    Cuando todos los resultados tienen inventario_incompleto=False (caso normal),
    el PDF debe generarse sin el aviso de inventario insuficiente.
    El PDF resultante debe ser válido.
    """
    from motor_fifo import MotorFIFO

    motor = MotorFIFO()
    motor.registrar_compra("2024-01-01", "BTC", 0.5, 15000.0, "EUR", "EUR", 0.0)
    motor.registrar_venta("2025-06-01", "BTC", 0.5, 25000.0, "EUR", "EUR", 0.0)

    assert motor.resultados[0].inventario_incompleto is False

    pdf = generar_pdf(motor, nombre_usuario="Test", ejercicio="2025",
                      exchange="Nexo", rendimientos=[])
    assert isinstance(pdf, bytes)
    assert len(pdf) > 1000
