"""
Unified email template system — minimal light design, Stripe/Linear-inspired.
All public functions return (html: str, text: str) tuples.
Inline styles only — email client compatibility.

Email types
───────────
  verification_email(verify_url)               → account email verification
  advisory_confirmation_email(advisory)         → advisory request received
  advisory_status_email(advisory, note)         → advisory status change
  processing_error_email(exchange, context)     → CSV/XLSX processing failure
  resource_request_confirmation_email(rr, res) → resource request received (user copy)
  resource_request_internal_email(rr, res)     → resource request notification (internal)
"""
from __future__ import annotations  # str | None union syntax on Python 3.9
import html as _html

_FF   = "-apple-system,'Segoe UI',Helvetica,Arial,sans-serif"
_BASE = "https://www.marianosevilla.com"

_NOTE_BORDER = {
    "neutral": "#cbd5e1",
    "info":    "#3b82f6",
    "warning": "#f59e0b",
    "success": "#059669",
    "error":   "#ef4444",
}


# ── Primitive HTML blocks ─────────────────────────────────────────────────────

def _p(content: str, *, last: bool = False) -> str:
    """Paragraph. content is raw HTML (caller escapes user values)."""
    mb = "0" if last else "16px"
    return (
        f'<p style="margin:0 0 {mb};font-size:15px;color:#374151;'
        f'line-height:1.75;font-family:{_FF};">{content}</p>'
    )


def _note(text: str, variant: str = "neutral") -> str:
    """Left-border highlighted note. text is plain — will be escaped."""
    color = _NOTE_BORDER.get(variant, _NOTE_BORDER["neutral"])
    return (
        f'<div style="border-left:3px solid {color};padding:12px 16px;'
        f'margin:20px 0 0;font-size:14px;color:#4b5563;line-height:1.65;'
        f'font-family:{_FF};">{_html.escape(text)}</div>'
    )


def _cta(text: str, url: str) -> str:
    """Dark CTA button — professional, not promotional."""
    return (
        f'<table cellpadding="0" cellspacing="0" role="presentation"'
        f' style="margin:24px 0 0;">'
        f'<tr><td style="background-color:#111827;border-radius:6px;">'
        f'<a href="{_html.escape(url)}" style="display:block;padding:13px 28px;'
        f'color:#ffffff;font-size:14px;font-weight:600;text-decoration:none;'
        f'font-family:{_FF};">{_html.escape(text)}</a>'
        f'</td></tr></table>'
    )


def _url_fallback(url: str) -> str:
    """Fallback URL display for email clients that strip buttons."""
    return (
        f'<p style="margin:12px 0 0;font-size:12px;color:#6b7280;'
        f'line-height:1.6;font-family:{_FF};">'
        f'Si el botón no funciona, copia este enlace:<br>'
        f'<span style="color:#059669;word-break:break-all;">{_html.escape(url)}</span></p>'
    )


def _ref(text: str) -> str:
    """Small reference line (solicitud ID, etc.)."""
    return (
        f'<p style="margin:20px 0 0;font-size:13px;color:#9ca3af;'
        f'font-family:{_FF};">{_html.escape(text)}</p>'
    )


# ── Footer builders ───────────────────────────────────────────────────────────

def _footer_html(*, legal: bool = False) -> str:
    out = (
        f'<p style="margin:0 0 5px;font-size:11px;color:#9ca3af;line-height:1.7;font-family:{_FF};">'
        f'Mariano Sevilla &middot; Gestión fiscal de criptomonedas &middot; '
        f'<a href="{_BASE}" style="color:#9ca3af;text-decoration:none;">marianosevilla.com</a></p>'
        f'<p style="margin:0;font-size:11px;color:#9ca3af;line-height:1.7;font-family:{_FF};">'
        f'Puedes responder directamente a este correo si necesitas ayuda.</p>'
    )
    if legal:
        out += (
            f'<p style="margin:6px 0 0;font-size:11px;color:#9ca3af;line-height:1.7;font-family:{_FF};">'
            f'<a href="{_BASE}/privacidad" style="color:#9ca3af;text-decoration:none;">Privacidad</a>'
            f'&nbsp;&middot;&nbsp;'
            f'<a href="{_BASE}/terminos" style="color:#9ca3af;text-decoration:none;">Términos</a>'
            f'&nbsp;&middot;&nbsp;'
            f'<a href="{_BASE}/account" style="color:#9ca3af;text-decoration:none;">Mi cuenta</a></p>'
        )
    return out


def _footer_text(*, legal: bool = False) -> str:
    lines = [
        "--",
        "Mariano Sevilla — marianosevilla.com",
        "Puedes responder directamente a este correo si necesitas ayuda.",
    ]
    if legal:
        lines += [
            "",
            f"Privacidad: {_BASE}/privacidad",
            f"Términos:   {_BASE}/terminos",
            f"Mi cuenta:  {_BASE}/account",
        ]
    return "\n".join(lines)


# ── Outer shell ───────────────────────────────────────────────────────────────

def _wrap(headline: str, body_html: str, *, legal_footer: bool = False) -> str:
    """Wraps body_html in the standard white/minimal email shell."""
    h = _html.escape(headline)
    return f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{h}</title>
</head>
<body style="margin:0;padding:0;background-color:#f9fafb;-webkit-text-size-adjust:100%;-ms-text-size-adjust:100%;">
  <table width="100%" cellpadding="0" cellspacing="0" role="presentation"
         style="background-color:#f9fafb;">
    <tr>
      <td align="center" style="padding:40px 20px 0;">
        <!--[if mso]><table width="560"><tr><td><![endif]-->
        <table width="100%" cellpadding="0" cellspacing="0" role="presentation"
               style="max-width:560px;">

          <!-- LOGO -->
          <tr>
            <td style="padding:0 0 18px;">
              <span style="font-size:14px;font-weight:700;color:#111827;letter-spacing:-.01em;
                            font-family:{_FF};">Mariano</span><span
                style="font-size:14px;font-weight:700;color:#059669;
                       font-family:{_FF};">.</span>
            </td>
          </tr>

          <!-- CARD -->
          <tr>
            <td style="background-color:#ffffff;border:1px solid #e5e7eb;
                        border-radius:6px;padding:32px 36px;">
              <h1 style="margin:0 0 20px;font-size:20px;font-weight:600;color:#111827;
                          line-height:1.4;font-family:{_FF};">{h}</h1>
              {body_html}
            </td>
          </tr>

          <!-- FOOTER -->
          <tr>
            <td style="padding:18px 4px 40px;">
              {_footer_html(legal=legal_footer)}
            </td>
          </tr>

        </table>
        <!--[if mso]></td></tr></table><![endif]-->
      </td>
    </tr>
  </table>
</body>
</html>"""


# ── Public email builders ─────────────────────────────────────────────────────

def verification_email(verify_url: str) -> tuple[str, str]:
    """Returns (html, text) for account email verification."""
    body_html = (
        _p("Para activar tu cuenta, haz clic en el botón.") +
        _cta("Verificar email", verify_url) +
        _url_fallback(verify_url) +
        _p(
            "El enlace caduca en 24 horas. "
            "Si no has creado esta cuenta, puedes ignorar este mensaje.",
            last=True,
        )
    )
    html = _wrap("Verifica tu dirección de email", body_html)
    text = "\n".join([
        "Verifica tu dirección de email",
        "",
        "Para activar tu cuenta, accede a este enlace:",
        verify_url,
        "",
        "El enlace caduca en 24 horas.",
        "Si no has creado esta cuenta, puedes ignorar este mensaje.",
        "",
        _footer_text(),
    ])
    return html, text


def advisory_confirmation_email(advisory) -> tuple[str, str]:
    """Returns (html, text) for advisory request confirmation."""
    name    = _html.escape(advisory.full_name)
    service = _html.escape(advisory.service_label())
    year    = _html.escape(str(advisory.tax_year))
    ref_id  = advisory.id

    body_html = (
        _p(f"Hola, {name}.") +
        _p(
            f"Hemos recibido tu solicitud de "
            f"<strong style='font-weight:600;color:#111827;'>{service}</strong> "
            f"para el ejercicio "
            f"<strong style='font-weight:600;color:#111827;'>{year}</strong>."
        ) +
        _p(
            "Revisaremos tu caso y te responderemos por email con los siguientes pasos. "
            "Si necesitamos documentación adicional, te lo indicaremos."
        ) +
        _p(
            "El servicio puede incluir una valoración previa por parte de Rafa, "
            "economista colegiado, antes de confirmar el precio final.",
            last=True,
        ) +
        _ref(f"Solicitud #{ref_id}")
    )
    html = _wrap("Solicitud recibida", body_html, legal_footer=True)
    text = "\n".join([
        "Solicitud recibida",
        "",
        f"Hola, {advisory.full_name}.",
        "",
        f"Hemos recibido tu solicitud de {advisory.service_label()} "
        f"para el ejercicio {advisory.tax_year}.",
        "",
        "Revisaremos tu caso y te responderemos por email con los siguientes pasos.",
        "Si necesitamos documentación adicional, te lo indicaremos.",
        "",
        f"Solicitud #{ref_id}",
        "",
        _footer_text(legal=True),
    ])
    return html, text


def advisory_status_email(
    advisory,
    note: str = "",
    app_base_url: str = _BASE,
) -> tuple[str | None, str | None]:
    """
    Returns (html, text) for an advisory status change notification.
    Returns (None, None) for statuses that don't generate email.
    """
    status     = advisory.status
    note_clean = (note or "").strip()

    _SKIPPED = ("pending_payment", "paid_received", "refunded")
    if status in _SKIPPED:
        return None, None

    name    = advisory.full_name
    name_h  = _html.escape(name)
    svc_h   = _html.escape(advisory.service_label())
    year_h  = _html.escape(str(advisory.tax_year))
    svc_t   = advisory.service_label()
    year_t  = str(advisory.tax_year)

    def _strong(s: str) -> str:
        return f"<strong style='font-weight:600;color:#111827;'>{s}</strong>"

    _CONFIGS: dict = {
        "under_review": {
            "headline":   "Tu caso está siendo revisado",
            "body_html":  (
                f"Hemos recibido tu solicitud de {_strong(svc_h)} "
                f"para el ejercicio {_strong(year_h)} y ya la estamos analizando. "
                f"Nuestro equipo valorará la mejor forma de ayudarte."
            ),
            "body_text":  (
                f"Hemos recibido tu solicitud de {svc_t} para el ejercicio {year_t} "
                f"y ya la estamos analizando."
            ),
            "next":       "No necesitas hacer nada por ahora. Te avisaremos cuando haya novedades.",
            "note_color": "info",
        },
        "waiting_user_info": {
            "headline":   "Necesitamos información adicional",
            "body_html":  (
                f"Para continuar con tu solicitud de {_strong(svc_h)} ({year_h}), "
                f"necesitamos que nos facilites algo más de información."
            ),
            "body_text":  (
                f"Para continuar con tu solicitud de {svc_t} ({year_t}), "
                f"necesitamos que nos facilites algo más de información."
            ),
            "next":       "Te contactaremos por email para indicarte exactamente qué necesitamos. Puedes responder directamente a este correo.",
            "note_color": "warning",
        },
        "in_progress": {
            "headline":   "Tu caso está en curso",
            "body_html":  (
                f"Tu solicitud de {_strong(svc_h)} para el ejercicio {_strong(year_h)} "
                f"ya está en manos del especialista. Trabajamos en tu caso con la atención que merece."
            ),
            "body_text":  (
                f"Tu solicitud de {svc_t} para el ejercicio {year_t} "
                f"ya está en manos del especialista."
            ),
            "next":       "Te informaremos cuando tengamos novedades.",
            "note_color": "info",
        },
        "completed": {
            "headline":   "Caso completado",
            "body_html":  (
                f"Hemos completado el servicio de {_strong(svc_h)} "
                f"para el ejercicio {_strong(year_h)}."
            ),
            "body_text":  f"Hemos completado el servicio de {svc_t} para el ejercicio {year_t}.",
            "next":       "Conserva la documentación que te hemos enviado y escríbenos si necesitas cualquier aclaración.",
            "note_color": "success",
        },
        "cancelled": {
            "headline":   "Solicitud cerrada",
            "body_html":  (
                f"Tu solicitud de {_strong(svc_h)} para el ejercicio {_strong(year_h)} "
                f"ha sido cerrada."
            ),
            "body_text":  f"Tu solicitud de {svc_t} para el ejercicio {year_t} ha sido cerrada.",
            "next":       "Si crees que hay un error o tienes alguna pregunta, no dudes en escribirnos.",
            "note_color": "neutral",
        },
    }

    cfg = _CONFIGS.get(status)
    if not cfg:
        return None, None

    body_html = (
        _p(f"Hola, {name_h}.") +
        _p(cfg["body_html"]) +
        ((_note(note_clean, cfg["note_color"])) if note_clean else "") +
        _p(cfg["next"], last=True) +
        _ref(f"Solicitud #{advisory.id}")
    )
    html = _wrap(cfg["headline"], body_html, legal_footer=True)

    text_parts = [
        cfg["headline"],
        "",
        f"Hola, {name}.",
        "",
        cfg["body_text"],
    ]
    if note_clean:
        text_parts += ["", note_clean]
    text_parts += [
        "",
        cfg["next"],
        "",
        f"Solicitud #{advisory.id}",
        "",
        _footer_text(legal=True),
    ]
    return html, "\n".join(text_parts)


def password_reset_email(reset_url: str) -> tuple[str, str]:
    """Returns (html, text) for password reset request."""
    body_html = (
        _p("Hemos recibido una solicitud para restablecer la contraseña de tu cuenta.") +
        _cta("Restablecer contraseña", reset_url) +
        _url_fallback(reset_url) +
        _note(
            "Este enlace caduca en 1 hora y solo puede usarse una vez. "
            "Si no has solicitado restablecer tu contraseña, puedes ignorar este mensaje "
            "— tu cuenta está segura.",
            "warning",
        ) +
        _p("Por seguridad, nunca compartimos tu contraseña por email.", last=True)
    )
    html = _wrap("Restablece tu contraseña", body_html)
    text = "\n".join([
        "Restablece tu contraseña",
        "",
        "Hemos recibido una solicitud para restablecer la contraseña de tu cuenta.",
        "",
        "Accede a este enlace para restablecer tu contraseña (caduca en 1 hora):",
        reset_url,
        "",
        "Este enlace es de un solo uso.",
        "Si no has solicitado restablecer tu contraseña, puedes ignorar este mensaje.",
        "",
        _footer_text(),
    ])
    return html, text


def processing_error_email(exchange: str, context_line: str) -> tuple[str, str]:
    """Returns (html, text) for a CSV/XLSX processing error notification."""
    exchange_display = (exchange or "tu exchange").capitalize()
    ctx = context_line or (
        "No hemos podido interpretar el formato del archivo."
    )

    body_html = (
        _p(
            f"Hemos intentado procesar tu archivo de "
            f"<strong style='font-weight:600;color:#111827;'>"
            f"{_html.escape(exchange_display)}</strong> "
            f"pero no hemos conseguido interpretarlo correctamente."
        ) +
        _p(_html.escape(ctx)) +
        _p("Si quieres ayudarnos a entender qué pasó, puedes responder a este correo con un poco de contexto:") +
        _note(
            "Qué intentabas hacer · Qué tipo de operaciones contiene el archivo · "
            "Si viste algún mensaje concreto en pantalla. "
            "No incluyas claves API ni información sensible.",
            "neutral",
        ) +
        _p("Gracias por ayudarnos a mejorar la herramienta.", last=True)
    )
    headline = f"Problema al procesar tu archivo de {exchange_display}"
    html = _wrap(headline, body_html)
    text = "\n".join([
        headline,
        "",
        f"Hemos intentado procesar tu archivo de {exchange_display} "
        f"pero no hemos conseguido interpretarlo correctamente.",
        "",
        ctx,
        "",
        "Si quieres ayudarnos a entender qué pasó, puedes responder a este correo:",
        "· Qué intentabas hacer",
        "· Qué tipo de operaciones contiene el archivo",
        "· Si viste algún mensaje concreto en pantalla",
        "",
        "No incluyas claves API ni información sensible.",
        "",
        "Gracias por ayudarnos a mejorar la herramienta.",
        "",
        _footer_text(),
    ])
    return html, text


def advisory_quote_email(advisory, payment_url: str) -> tuple[str, str]:
    """Email al cliente con el presupuesto y el link de pago PayPal."""
    name         = _html.escape(advisory.full_name)
    service      = _html.escape(advisory.service_label())
    year         = _html.escape(str(advisory.tax_year))
    amount_euros = f"{advisory.quoted_amount / 100:.2f}".replace(".", ",")
    ref_id       = advisory.id

    amount_block = (
        f'<div style="background:#f9fafb;border:1px solid #e5e7eb;border-radius:6px;'
        f'padding:20px 24px;margin:20px 0;">'
        f'<p style="margin:0 0 4px;font-size:12px;color:#6b7280;font-family:{_FF};">IMPORTE</p>'
        f'<p style="margin:0;font-size:28px;font-weight:700;color:#111827;'
        f'font-family:{_FF};">{_html.escape(amount_euros)}&nbsp;€</p>'
        f'<p style="margin:6px 0 0;font-size:13px;color:#6b7280;font-family:{_FF};">'
        f'{service} &middot; Ejercicio {year}</p>'
        f'</div>'
    )

    message_block = ""
    if advisory.quote_message:
        message_block = _note(advisory.quote_message, variant="info")

    expiry_block = ""
    if advisory.quote_expires_at:
        exp = advisory.quote_expires_at.strftime("%d/%m/%Y")
        expiry_block = _p(
            f'Este presupuesto es válido hasta el <strong style="font-weight:600;color:#111827;">'
            f'{_html.escape(exp)}</strong>.'
        )

    body_html = (
        _p(f"Hola, {name}.") +
        _p("Hemos revisado tu caso y ya tienes el presupuesto listo.") +
        amount_block +
        message_block +
        expiry_block +
        _p("Para confirmar el servicio, haz clic en el botón y completa el pago con PayPal:") +
        _cta("Pagar con PayPal", payment_url) +
        _url_fallback(payment_url) +
        _p(
            "El pago es seguro y está procesado por PayPal. "
            "Una vez confirmado, Rafa comenzará a trabajar en tu caso.",
            last=True,
        ) +
        _ref(f"Solicitud #{ref_id}")
    )
    html = _wrap("Tu presupuesto de asesoramiento fiscal", body_html, legal_footer=True)

    exp_line = ""
    if advisory.quote_expires_at:
        exp_line = f"Válido hasta: {advisory.quote_expires_at.strftime('%d/%m/%Y')}\n"

    msg_line = f"\nMensaje de Rafa:\n{advisory.quote_message}\n" if advisory.quote_message else ""

    text = "\n".join([
        "Tu presupuesto de asesoramiento fiscal",
        "",
        f"Hola, {advisory.full_name}.",
        "",
        "Hemos revisado tu caso y ya tienes el presupuesto listo.",
        "",
        f"Importe: {amount_euros} €",
        f"Servicio: {advisory.service_label()}",
        f"Ejercicio: {advisory.tax_year}",
        exp_line.strip(),
        msg_line.strip(),
        "",
        "Para confirmar el servicio, accede al siguiente enlace y completa el pago:",
        payment_url,
        "",
        f"Solicitud #{ref_id}",
        "",
        _footer_text(legal=True),
    ])
    return html, text


def advisory_payment_confirmed_email(advisory) -> tuple[str, str]:
    """Email al cliente confirmando que el pago se ha recibido y el trabajo comenzará."""
    name    = _html.escape(advisory.full_name)
    service = _html.escape(advisory.service_label())
    year    = _html.escape(str(advisory.tax_year))
    ref_id  = advisory.id
    amount  = ""
    if advisory.amount_paid:
        amount = f"{advisory.amount_paid / 100:.2f}".replace(".", ",")

    amount_block = ""
    if amount:
        amount_block = (
            f'<div style="background:#f0fdf4;border:1px solid #bbf7d0;border-radius:6px;'
            f'padding:16px 20px;margin:20px 0;">'
            f'<p style="margin:0 0 2px;font-size:12px;color:#16a34a;font-family:{_FF};">PAGO CONFIRMADO</p>'
            f'<p style="margin:0;font-size:24px;font-weight:700;color:#111827;'
            f'font-family:{_FF};">{_html.escape(amount)}&nbsp;€</p>'
            f'</div>'
        )

    body_html = (
        _p(f"Hola, {name}.") +
        _p("Hemos confirmado tu pago. Gracias.") +
        amount_block +
        _p(
            f"Rafa comenzará a trabajar en tu <strong style='font-weight:600;color:#111827;'>"
            f"{service}</strong> para el ejercicio "
            f"<strong style='font-weight:600;color:#111827;'>{year}</strong> "
            f"y te contactará por email cuando tenga novedades."
        ) +
        _p("Si tienes alguna pregunta, responde directamente a este correo.", last=True) +
        _ref(f"Solicitud #{ref_id}")
    )
    html = _wrap("Pago confirmado — comenzamos", body_html, legal_footer=True)
    text = "\n".join([
        "Pago confirmado — comenzamos",
        "",
        f"Hola, {advisory.full_name}.",
        "",
        "Hemos confirmado tu pago. Gracias.",
        *(([f"Importe: {amount} €", ""] if amount else [])),
        f"Rafa comenzará a trabajar en tu {advisory.service_label()} "
        f"para el ejercicio {advisory.tax_year} "
        "y te contactará por email cuando tenga novedades.",
        "",
        "Si tienes alguna pregunta, responde directamente a este correo.",
        "",
        f"Solicitud #{ref_id}",
        "",
        _footer_text(legal=True),
    ])
    return html, text


def advisory_payment_internal_email(advisory) -> tuple[str, str]:
    """Email interno a Rafa cuando un cliente completa el pago."""
    service  = advisory.service_label()
    ref_id   = advisory.id
    amount   = f"{advisory.amount_paid / 100:.2f} €" if advisory.amount_paid else "—"
    provider = (advisory.payment_provider or "").upper()
    capture  = advisory.paypal_capture_id or advisory.stripe_payment_intent_id or "—"
    admin_url = f"{_BASE}/admin/asesoramiento"

    lines = [
        f"Nombre: {advisory.full_name}",
        f"Email:  {advisory.email}",
        f"Servicio: {service} · Ejercicio {advisory.tax_year}",
        f"Importe: {amount} ({provider})",
        f"Capture ID: {capture}",
        f"Solicitud #{ref_id}",
    ]
    detail = "\n".join(f"  {l}" for l in lines)

    body_html = (
        _p(f"<strong style='font-weight:600;color:#111827;'>{_html.escape(advisory.full_name)}</strong> "
           f"ha completado el pago de "
           f"<strong style='font-weight:600;color:#111827;'>{_html.escape(amount)}</strong>.") +
        _note("\n".join(lines), variant="success") +
        _cta("Ver expediente en el panel", admin_url)
    )
    html = _wrap(f"💰 Pago confirmado — {advisory.full_name}", body_html)
    text = "\n".join([
        f"Pago confirmado — {advisory.full_name}",
        "",
        f"{advisory.full_name} ha completado el pago de {amount}.",
        "",
        detail,
        "",
        f"Panel: {admin_url}",
        "",
        _footer_text(),
    ])
    return html, text


# ── BIBLIOTECA DE RECURSOS ────────────────────────────────────────────────────

def resource_request_confirmation_email(rr, resource) -> tuple[str, str]:
    """Confirmación al usuario de que su solicitud de recurso fue recibida."""
    name     = _html.escape(rr.name)
    res_title = _html.escape(resource.title)

    body_html = (
        _p(f"Hola, {name}.") +
        _p(
            f"Hemos recibido tu solicitud para el recurso "
            f"<strong style='font-weight:600;color:#111827;'>{res_title}</strong>."
        ) +
        _p(
            "Revisaremos los datos que nos has facilitado y nos pondremos en contacto "
            "contigo cuando hayamos verificado tu solicitud."
        ) +
        _p(
            "Si indicaste un usuario de Telegram, es posible que te contactemos por ahí "
            "para agilizar el proceso.",
            last=True,
        ) +
        _ref(f"Solicitud #{rr.id}")
    )
    html = _wrap(f"Solicitud recibida — {res_title}", body_html, legal_footer=True)
    text = "\n".join([
        f"Solicitud recibida — {resource.title}",
        "",
        f"Hola, {rr.name}.",
        "",
        f"Hemos recibido tu solicitud para el recurso \"{resource.title}\".",
        "",
        "Revisaremos los datos que nos has facilitado y nos pondremos en contacto "
        "contigo cuando hayamos verificado tu solicitud.",
        "",
        "Si indicaste un usuario de Telegram, es posible que te contactemos por ahí.",
        "",
        f"Solicitud #{rr.id}",
        "",
        _footer_text(legal=True),
    ])
    return html, text


def resource_request_internal_email(rr, resource, admin_url: str = _BASE) -> tuple[str, str]:
    """Notificación interna cuando llega una solicitud de recurso."""
    res_title = _html.escape(resource.title)
    name      = _html.escape(rr.name)
    bitvavo   = _html.escape(rr.bitvavo_status_label())
    uid_val   = _html.escape(rr.uid or ("No sabe dónde encontrarlo" if rr.uid_unknown else "—"))
    telegram  = _html.escape(rr.telegram_user or "—")
    source    = _html.escape(rr.source or "—")
    panel     = f"{admin_url}/admin/recursos"

    rows_html = "".join(
        f"<tr><td style='padding:6px 10px;color:#6b7280;font-size:13px;white-space:nowrap'>{k}</td>"
        f"<td style='padding:6px 10px;font-size:13px;word-break:break-word'>{v}</td></tr>"
        for k, v in [
            ("ID",        f"#{rr.id}"),
            ("Recurso",   res_title),
            ("Nombre",    name),
            ("Email",     _html.escape(rr.email)),
            ("Exchange",  _html.escape(rr.exchange or "—")),
            ("Bitvavo",   bitvavo),
            ("UID",       uid_val),
            ("Telegram",  telegram),
            ("Origen",    source),
            ("Consiente comunicaciones", "Sí" if rr.marketing_consent else "No"),
        ]
    )
    table_html = (
        "<table style='border-collapse:collapse;width:100%;margin:16px 0'>"
        f"{rows_html}"
        "</table>"
    )
    body_html = (
        _p(f"Nueva solicitud de <strong style='font-weight:600'>{res_title}</strong>.") +
        table_html +
        _p(f"<a href='{panel}' style='color:#4f46e5'>Ver en el panel de admin →</a>", last=True)
    )
    html = _wrap(
        f"[Recursos] Nueva solicitud #{rr.id} — {resource.title}",
        body_html,
    )
    text_lines = [
        f"[Recursos] Nueva solicitud #{rr.id} — {resource.title}",
        "",
        f"Nombre:    {rr.name}",
        f"Email:     {rr.email}",
        f"Recurso:   {resource.title}",
        f"Exchange:  {rr.exchange or '—'}",
        f"Bitvavo:   {rr.bitvavo_status_label()}",
        f"UID:       {rr.uid or ('No sabe dónde encontrarlo' if rr.uid_unknown else '—')}",
        f"Telegram:  {rr.telegram_user or '—'}",
        f"Origen:    {rr.source or '—'}",
        f"Newsletter: {'Sí' if rr.marketing_consent else 'No'}",
        "",
        f"Panel: {panel}",
        "",
        _footer_text(),
    ]
    return html, "\n".join(text_lines)
