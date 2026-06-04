"""
auth.py — Helpers y decoradores centralizados de autorización.

Centraliza toda la lógica de comprobación de roles en un único lugar.
Las funciones de aplicación (app.py, blueprints) importan desde aquí
en lugar de definir su propia lógica de permisos.

Diseño de Fase 1:
  - Fuente primaria:  campo `role` del modelo User en BD.
  - Fuente de respaldo: variables de entorno ADMIN_EMAILS y FISCAL_ADVISOR_EMAILS
    (compatibilidad hacia atrás — se mantienen hasta migración completa).
  - Roles reconocidos: 'user', 'fiscal_advisor', 'admin'.

Uso
---
    from auth import require_admin, require_fiscal_advisor
    from auth import require_admin_page, require_fiscal_advisor_page

    # API (devuelve 403 en fallo)
    @require_admin
    def mi_endpoint_admin(): ...

    # Página HTML (redirige a /dashboard en fallo)
    @require_admin_page
    def mi_pagina_admin(): ...
"""

import os
from functools import wraps
from typing import Optional

from flask import abort, redirect
from flask_login import current_user, login_required

# ── Conjuntos de emails por variable de entorno ───────────────────────────────
# Se leen UNA vez en tiempo de importación, igual que en app.py original.
# En tests: definir la variable de entorno ANTES de importar este módulo.

ADMIN_EMAILS: frozenset = frozenset(
    e.strip().lower()
    for e in os.environ.get("ADMIN_EMAILS", "").split(",")
    if e.strip()
)

FISCAL_ADVISOR_EMAILS: frozenset = frozenset(
    e.strip().lower()
    for e in os.environ.get("FISCAL_ADVISOR_EMAILS", "").split(",")
    if e.strip()
)


# ── Funciones de comprobación de roles ───────────────────────────────────────

def _role_is_admin() -> bool:
    """
    True si el usuario autenticado tiene acceso de administrador.

    Orden de comprobación:
      1. Fuente primaria: campo role == 'admin' en la BD.
      2. Fallback:        email en ADMIN_EMAILS (variable de entorno).
    """
    if not current_user.is_authenticated:
        return False
    if getattr(current_user, "role", "user") == "admin":
        return True
    return current_user.email.strip().lower() in ADMIN_EMAILS


def _role_is_fiscal_advisor() -> bool:
    """
    True si el usuario autenticado tiene acceso de asesor fiscal o superior.

    Orden de comprobación:
      1. Fuente primaria: campo role in {'admin', 'fiscal_advisor'} en la BD.
      2. Fallback:        email en FISCAL_ADVISOR_EMAILS o en ADMIN_EMAILS.

    Los admins siempre tienen acceso de asesor (jerarquía admin > fiscal_advisor > user).
    """
    if not current_user.is_authenticated:
        return False
    role = getattr(current_user, "role", "user")
    if role in ("admin", "fiscal_advisor"):
        return True
    email = current_user.email.strip().lower()
    return email in FISCAL_ADVISOR_EMAILS or email in ADMIN_EMAILS


def _has_any_role(*roles: str) -> bool:
    """
    True si el usuario autenticado posee al menos uno de los roles dados.
    'admin' incluye siempre acceso de 'fiscal_advisor' (jerarquía).
    """
    for role in roles:
        if role == "admin" and _role_is_admin():
            return True
        if role == "fiscal_advisor" and _role_is_fiscal_advisor():
            return True
    return False


# ── Fábrica de decoradores ────────────────────────────────────────────────────

def require_roles(
    *roles: str,
    on_fail_redirect: Optional[str] = None,
    on_fail_abort: int = 403,
):
    """
    Decorador: exige autenticación y que el usuario tenga alguno de los roles dados.

    Parámetros
    ----------
    *roles : str
        Uno o más de: 'admin', 'fiscal_advisor'.
        'admin' incluye acceso de 'fiscal_advisor' automáticamente.
    on_fail_redirect : str, opcional
        URL a la que redirigir si falla la autorización.
        Usar para páginas HTML.
    on_fail_abort : int, por defecto 403
        Código HTTP con el que abortar si on_fail_redirect no está definido.
        Usar para endpoints de API.

    Ejemplos
    --------
    @require_roles('admin')
    @require_roles('fiscal_advisor')
    @require_roles('admin', on_fail_redirect='/dashboard')
    @require_roles('admin', on_fail_abort=404)   # ocultar existencia de la ruta
    """
    def decorator(f):
        @wraps(f)
        @login_required
        def wrapper(*args, **kwargs):
            if not _has_any_role(*roles):
                if on_fail_redirect is not None:
                    return redirect(on_fail_redirect)
                abort(on_fail_abort)
            return f(*args, **kwargs)
        return wrapper
    return decorator


# ── Decoradores listos para usar ──────────────────────────────────────────────

# Para endpoints de API — devuelve 403 en fallo
require_admin          = require_roles("admin")
require_fiscal_advisor = require_roles("fiscal_advisor")

# Para páginas HTML — redirige a /dashboard en fallo
require_admin_page          = require_roles("admin",          on_fail_redirect="/dashboard")
require_fiscal_advisor_page = require_roles("fiscal_advisor", on_fail_redirect="/dashboard")
