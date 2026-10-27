"""Ensure all shared FIFO tools avoid unqualified promises of free reports."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def test_tool_footer_does_not_promise_free_reports():
    template = (ROOT / "templates" / "tool.html").read_text(encoding="utf-8")
    faq = (ROOT / "static" / "faq.html").read_text(encoding="utf-8")
    assert "Una herramienta gratuita de" not in template
    assert "Una herramienta de informes FIFO de" in template
    assert "El registro no significa que todos los informes, descargas o servicios estén incluidos" in faq
