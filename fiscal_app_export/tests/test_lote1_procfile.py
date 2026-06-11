"""
LOTE 1 — Tarea 2: configuración explícita de Gunicorn.

Guarda de regresión: el Procfile debe declarar explícitamente worker class,
workers, threads y timeout. Con los defaults de gunicorn (1 worker sync,
timeout 30 s) un solo análisis largo bloqueaba toda la aplicación y los
análisis del Modelo 721 morían en 502 por el throttle de CoinGecko.

Restricción importante: workers debe seguir siendo 1 mientras el lock
anti-concurrencia (_analisis_en_curso) y el rate limiter (memory://) sean
por proceso. La concurrencia se obtiene vía threads (gthread).
"""

import os
import re

_PROCFILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "Procfile")


def _linea_web() -> str:
    with open(_PROCFILE, encoding="utf-8") as f:
        for linea in f:
            if linea.startswith("web:"):
                return linea
    raise AssertionError("Procfile sin línea 'web:'")


def test_worker_class_gthread():
    assert "--worker-class gthread" in _linea_web()


def test_workers_es_uno():
    """1 worker: el lock por usuario y el limiter memory:// son por proceso."""
    m = re.search(r"--workers (\d+)", _linea_web())
    assert m, "falta --workers explícito"
    assert m.group(1) == "1"


def test_threads_configurados():
    m = re.search(r"--threads (\d+)", _linea_web())
    assert m, "falta --threads explícito"
    assert int(m.group(1)) >= 4


def test_timeout_suficiente_para_721():
    """/api/721 con throttle CoinGecko (1,2 s/ticker) supera los 30 s default."""
    m = re.search(r"--timeout (\d+)", _linea_web())
    assert m, "falta --timeout explícito"
    assert int(m.group(1)) >= 120
