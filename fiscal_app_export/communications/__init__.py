from flask import Blueprint

comms_bp = Blueprint("communications", __name__)

from . import routes  # noqa: E402, F401  — registers routes on comms_bp
