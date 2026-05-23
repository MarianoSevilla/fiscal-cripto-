"""
Tests para ClasificadorNexo — verificación de detección de ejercicios fiscales.

Caso crítico: un CSV con valores USD como $2039.59 o importes como -2028.29
NO debe generar años ficticios en la lista de ejercicios detectados.
"""

import re
import tempfile
import os
from datetime import datetime
from typing import List, Set

import pytest

from fiscal_app_export.clasificador_nexo import ClasificadorNexo


# ── FIXTURE REDUCIDO ──────────────────────────────────────────────────────────
# Contiene:
#   - Fechas reales en 2024, 2025 y 2026
#   - USD Equivalent con valores que parecen años (2027.46, 2033.78, 2039.59)
#   - Input Amount con valor que parece año (-2028.293015)
#   - Output Amount con valor que parece año (2023.234928) ← también en rango real
# El clasificador debe usar SÓLO la columna "Date / Time (UTC)" para extraer fechas.

NEXO_CSV_FIXTURE = """\
Transaction,Type,Input Currency,Input Amount,Output Currency,Output Amount,USD Equivalent,Fee,Fee Currency,Details,Date / Time (UTC)
NXTaaa111bbb222ccc333,Interest,NEXO,0.28243817,NEXO,0.28243817,$0.25,-,-,"approved / NEXO Interest Earned",2026-05-23 05:00:00
NXTbbb222ccc333ddd444,Interest,xUSD,-2.60000000,xUSD,2.60000000,$2.60,-,-,"approved / Interest",2026-01-15 00:00:00
NXTccc333ddd444eee555,Interest,NEXO,1.50000000,NEXO,1.50000000,$2027.46,-,-,"approved / NEXO Interest Earned",2025-11-20 05:00:00
NXTddd444eee555fff666,Exchange,EUR,-2028.293015,BTC,0.03100000,$2033.78,-,-,"approved / Exchange",2025-06-10 14:30:00
NXTeee555fff666ggg777,Exchange,BTC,-0.01000000,EUR,2023.234928,$2039.59,-,-,"approved / Exchange",2024-12-01 09:00:00
NXTfff666ggg777hhh888,Interest,xUSD,-3.00000000,xUSD,3.00000000,$3.00,-,-,"approved / Interest",2024-03-15 00:00:00
"""


def _csv_to_tmpfile(content: str) -> str:
    """Escribe el CSV en un fichero temporal y devuelve la ruta."""
    fd, path = tempfile.mkstemp(suffix=".csv")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(content)
    return path


# ── TESTS ─────────────────────────────────────────────────────────────────────

class TestClasificadorNexoEjercicios:

    def setup_method(self):
        path = _csv_to_tmpfile(NEXO_CSV_FIXTURE)
        self.clasificador = ClasificadorNexo(path).clasificar()
        os.unlink(path)

    def _all_fechas(self):
        """Recopila todas las fechas generadas por el clasificador."""
        fechas = []
        for lista in (
            self.clasificador.compraventas,
            self.clasificador.rendimientos,
            self.clasificador.movimientos,
            self.clasificador.swaps,
        ):
            fechas.extend(str(op.fecha) for op in lista)
        return fechas

    def test_solo_años_reales_en_fechas(self):
        """Solo deben aparecer años 2024, 2025 y 2026 en las fechas procesadas."""
        fechas = self._all_fechas()
        assert fechas, "El clasificador no generó ninguna operación"
        años_detectados = {int(f[:4]) for f in fechas if f and len(f) >= 4}
        assert años_detectados == {2024, 2025, 2026}, (
            f"Años detectados incorrectos: {sorted(años_detectados)}"
        )

    def test_no_años_falsos_de_importes(self):
        """Los valores USD (2027, 2033, 2039) e importes (2028) no deben aparecer como años."""
        fechas = self._all_fechas()
        años_falsos = {2027, 2028, 2033, 2039}
        años_en_fechas = {int(f[:4]) for f in fechas if f and len(f) >= 4}
        presentes = años_falsos & años_en_fechas
        assert not presentes, (
            f"Años falsos presentes en fechas: {sorted(presentes)}"
        )

    def test_total_operaciones_fixture(self):
        """El fixture tiene 6 filas → debe producir operaciones sin crashear."""
        resumen = self.clasificador.resumen()
        total = (
            resumen["compraventas"]
            + resumen["rendimientos"]
            + resumen["movimientos"]
            + resumen["swaps"]
            + resumen["desconocidas"]
        )
        assert total > 0, "El clasificador no procesó ninguna operación"


class TestExtractYearsRegex:
    """
    Replica en Python la lógica de extractYearsFromCSV del JS corregido.
    Verifica que la regex de fecha (YYYY-MM-DD) no captura importes ni IDs.
    """

    AÑO_MIN = 2009
    AÑO_MAX_FN = staticmethod(lambda: datetime.now().year)

    @staticmethod
    def _extract_years_correcto(text: str) -> List[int]:
        """Replica la regex JS corregida: sólo captura YYYY cuando va seguido de -MM-DD."""
        current_year = datetime.now().year
        years: Set[int] = set()
        for m in re.finditer(r'\b(20(?:0[9]|[12][0-9]|3[0-9]))-\d{2}-\d{2}\b', text):
            yr = int(m.group(1))
            if 2009 <= yr <= current_year:
                years.add(yr)
        return sorted(years)

    @staticmethod
    def _extract_years_buggy(text: str) -> List[int]:
        """Replica la regex JS original (buggy): captura CUALQUIER 20xx."""
        years: Set[int] = set()
        for m in re.finditer(r'\b20(0[9]|[12][0-9]|3[0-9])\b', text):
            years.add(int("20" + m.group(1)))
        return sorted(years)

    def test_regex_corregida_no_captura_importes(self):
        """La regex corregida ignora importes USD como $2039.59."""
        text = NEXO_CSV_FIXTURE
        años = self._extract_years_correcto(text)
        assert 2039 not in años, "2039 de USD Equivalent no debe aparecer"
        assert 2033 not in años, "2033 de USD Equivalent no debe aparecer"
        assert 2028 not in años, "2028 de Input Amount no debe aparecer"
        assert 2027 not in años, "2027 de USD Equivalent no debe aparecer"

    def test_regex_corregida_captura_años_reales(self):
        """La regex corregida captura los años reales del CSV."""
        text = NEXO_CSV_FIXTURE
        años = self._extract_years_correcto(text)
        assert set(años) == {2024, 2025, 2026}, (
            f"Se esperaban [2024, 2025, 2026], se obtuvieron {años}"
        )

    def test_regex_buggy_si_capturaba_falsos(self):
        """Documenta el comportamiento anterior: la regex buggy SÍ capturaba años falsos."""
        text = NEXO_CSV_FIXTURE
        años_buggy = self._extract_years_buggy(text)
        # El bug existía: había años fuera de {2024, 2025, 2026}
        assert set(años_buggy) - {2024, 2025, 2026}, (
            "Se esperaba que la regex buggy produjera años falsos (confirma que el bug existía)"
        )

    def test_limite_año_maximo(self):
        """Años futuros (mayores que el año actual) se descartan."""
        current_year = datetime.now().year
        future_year = current_year + 1
        text = f"algo,{future_year}-06-15,dato"
        años = self._extract_years_correcto(text)
        assert future_year not in años

    def test_limite_año_minimo(self):
        """Años anteriores a 2009 se descartan."""
        text = "algo,2008-12-31,dato"
        años = self._extract_years_correcto(text)
        assert 2008 not in años
