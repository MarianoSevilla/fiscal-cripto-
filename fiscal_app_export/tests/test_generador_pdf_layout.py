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
