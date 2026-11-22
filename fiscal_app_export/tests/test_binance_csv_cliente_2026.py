"""Regresión del CSV Binance ES 2026 y del selector de ejercicios.

Todos los datos de prueba son sintéticos. No incorpora registros del cliente.
"""
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from clasificador_binance_tx import ClasificadorBinanceTx


HEADER_2026 = "ID de usuario,Hora,Cuenta,Operación,Moneda,Cambiar,Comentario\n"
HEADER_CANONICA = "ID de usuario,Tiempo,Cuenta,Operación,Moneda,Cambio,Observación\n"


def _csv(tmp_path, header, contenido):
    path = tmp_path / "historial_sintetico.csv"
    path.write_text("\ufeff" + header + contenido, encoding="utf-8")
    return path


def test_csv_binance_2026_admite_cabeceras_originales_sin_perder_cantidades(tmp_path):
    filas = (
        "12345678,2026-02-01 09:00:00,Spot,Transaction Spend,EUR,-150,\n"
        "12345678,2026-02-01 09:00:00,Spot,Transaction Buy,BTC,0.003,\n"
        "12345678,2026-02-02 09:00:00,Spot,Simple Earn Flexible Interest,BTC,0.000001,\n"
    )
    actual = ClasificadorBinanceTx(str(_csv(tmp_path, HEADER_2026, filas))).clasificar()
    assert len(actual.compraventas) == 1
    assert len(actual.rendimientos) == 1
    assert not actual.desconocidas
    assert actual.compraventas[0].importe == 150
    assert actual.compraventas[0].cantidad == 0.003

    canonico = ClasificadorBinanceTx(str(_csv(tmp_path, HEADER_CANONICA, filas))).clasificar()
    assert actual.resumen() == canonico.resumen()
    assert actual.compraventas == canonico.compraventas


def test_comentario_2026_preserva_identificador_de_wallet(tmp_path):
    filas = (
        "12345678,2025-04-02 10:00:00,Spot,Buy Crypto With Fiat,EUR,-600,Wallet/FAKE123\n"
        "12345678,2025-04-02 10:00:00,Spot,Buy Crypto With Fiat,BTC,0.02,Wallet/FAKE123\n"
    )
    actual = ClasificadorBinanceTx(str(_csv(tmp_path, HEADER_2026, filas))).clasificar()
    assert len(actual.compraventas) == 1
    assert actual.compraventas[0].importe == 600
    assert actual.compraventas[0].cantidad == 0.02
    assert not actual.desconocidas


def test_selector_de_binance_lee_csv_completo_y_no_solo_un_megabyte():
    template = (Path(__file__).resolve().parents[1] / "templates" / "tool.html").read_text(
        encoding="utf-8"
    )
    bloque = template.split("async function extractYearsFromCSV(file)", 1)[1].split(
        "// Listener delegado", 1
    )[0]
    assert "reader.readAsText(file, 'utf-8');" in bloque
    assert "readAsText(file.slice(" not in bloque

    # Reproduce el fallo de un CSV multi-anual de más de 1 MiB con fechas
    # posteriores a 2022 al final, usando únicamente movimientos ficticios.
    cabecera = HEADER_2026
    primeras = (
        "12345678,2021-12-03 10:00:00,Spot,Simple Earn Flexible Interest,BTC,0.000001,\n"
        + ("12345678,2022-01-01 10:00:00,Spot,Simple Earn Flexible Interest,BTC,0.000001,\n" * 15000)
    )
    ultimas = "".join(
        f"12345678,{year}-02-01 10:00:00,Spot,Simple Earn Flexible Interest,BTC,0.000001,\n"
        for year in (2023, 2024, 2025, 2026)
    )
    csv_texto = cabecera + primeras + ultimas
    patron = re.compile(r"\b(20(?:0[9]|[12][0-9]|3[0-9]))-\d{2}-\d{2}\b")
    primeros_anios = set(patron.findall(csv_texto[:1024 * 1024]))
    todos_los_anios = set(patron.findall(csv_texto))
    assert primeros_anios == {"2021", "2022"}
    assert todos_los_anios == {"2021", "2022", "2023", "2024", "2025", "2026"}
