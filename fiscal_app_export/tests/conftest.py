"""
conftest.py compartido para todos los tests de fiscal_app_export.

Resetea el storage in-memory del rate limiter antes de cada módulo de
test para evitar que los contadores acumulados de un módulo causen 429
inesperados en el siguiente.
"""

import sys
import os
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


@pytest.fixture(autouse=True, scope="function")
def reset_rate_limiter_por_test():
    """
    Limpia los contadores del rate limiter antes de cada test.

    Necesario porque el storage in-memory del limiter persiste entre tests
    y las llamadas acumuladas (login + API) pueden superar el límite global
    de "20 por hora" cuando se ejecutan varios módulos de tests juntos.
    Esta función es trivialmente rápida (un dict.clear()) y no afecta
    al rendimiento del test suite.
    """
    try:
        from app import limiter
        limiter.reset()
    except Exception:
        pass
    yield
