"""U04-PREFREEZE: unconditional suspension, with no configuration off switch.

This release knows only the U03 schema. Removing the suspension requires a
separately reviewed code release; environment variables cannot enable payments.
"""
from functools import wraps

from flask import jsonify, make_response, send_from_directory
from werkzeug.exceptions import ServiceUnavailable

SUSPENSION_MESSAGE = (
    "Los pagos de asesoramiento están temporalmente suspendidos por mantenimiento. "
    "Si ya has autorizado un pago en PayPal, no vuelvas a realizarlo. "
    "Estamos verificando las operaciones pendientes."
)


def advisory_financial_prefreeze(*, html=False):
    """Never enter the wrapped handler, read its payload, or consult its record.

    Put inside authentication/authorization decorators to preserve their checks.
    Webhooks deliberately receive a non-2xx without signature verification or
    acknowledgement: nothing has been accepted, processed, or queued locally.
    """
    def decorate(handler):
        @wraps(handler)
        def suspended(*args, **kwargs):
            if html:
                response = make_response(send_from_directory("static", "pagar.html"), 503)
            else:
                response = make_response(jsonify(
                    error=SUSPENSION_MESSAGE,
                    code="advisory_financial_suspended",
                    state="reconciliation_pending",
                ), 503)
            response.headers["Cache-Control"] = "no-store"
            # Advisory only: provider retry schedules are provider-controlled.
            response.headers["Retry-After"] = "300"
            return response
        return suspended
    return decorate


def refuse_advisory_financial_operation():
    """Defense for direct/indirect helper calls, before external I/O or writes."""
    raise ServiceUnavailable(description=SUSPENSION_MESSAGE)
