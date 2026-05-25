"""
HTML/text template renderer for campaign emails.
Design: minimal light, Stripe/Linear-inspired — optimised for deliverability.
Inline styles only — email client compatibility.
"""
import re
import html as _html

_BODY_STYLE = (
    "margin:0 0 16px;font-size:15px;color:#374151;line-height:1.75;"
    "font-family:-apple-system,'Segoe UI',Helvetica,Arial,sans-serif;"
)
_BODY_LAST = (
    "margin:0;font-size:15px;color:#374151;line-height:1.75;"
    "font-family:-apple-system,'Segoe UI',Helvetica,Arial,sans-serif;"
)


def _body_to_paragraphs(raw: str) -> str:
    """Convert textarea body (double-newline = paragraph, single = line break) to HTML."""
    escaped    = _html.escape(raw)
    paragraphs = [p.strip() for p in re.split(r"\n{2,}", escaped) if p.strip()]
    if not paragraphs:
        return ""
    parts = [
        f'<p style="{_BODY_STYLE}">{p.replace(chr(10), "<br>")}</p>'
        for p in paragraphs[:-1]
    ]
    parts.append(
        f'<p style="{_BODY_LAST}">{paragraphs[-1].replace(chr(10), "<br>")}</p>'
    )
    return "".join(parts)


def render_campaign_html(campaign, unsubscribe_url: str) -> str:
    """Renders the full HTML email — minimal light design for maximum deliverability."""
    subject_esc  = _html.escape(campaign.subject)
    preview_text = _html.escape(campaign.preview_text or "")
    preview_snippet = (
        f'<div style="display:none;max-height:0;overflow:hidden;mso-hide:all;">'
        f'{preview_text}&nbsp;&#8204;&#8204;&#8204;</div>'
        if preview_text else ""
    )
    body_html = _body_to_paragraphs(campaign.body)

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{subject_esc}</title>
</head>
<body style="margin:0;padding:0;background-color:#f9fafb;-webkit-text-size-adjust:100%;-ms-text-size-adjust:100%;">
  {preview_snippet}
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
                            font-family:-apple-system,'Segoe UI',Helvetica,Arial,sans-serif;"
              >Mariano</span><span
                style="font-size:14px;font-weight:700;color:#059669;
                       font-family:-apple-system,'Segoe UI',Helvetica,Arial,sans-serif;">.</span>
            </td>
          </tr>

          <!-- CARD -->
          <tr>
            <td style="background-color:#ffffff;border:1px solid #e5e7eb;border-radius:6px;
                        padding:32px 36px;">
              <h1 style="margin:0 0 20px;font-size:20px;font-weight:600;color:#111827;
                          line-height:1.4;
                          font-family:-apple-system,'Segoe UI',Helvetica,Arial,sans-serif;">
                {subject_esc}
              </h1>
              {body_html}
              <table cellpadding="0" cellspacing="0" role="presentation"
                     style="margin:24px 0 0;width:100%;">
                <tr>
                  <td style="border-top:1px solid #f3f4f6;padding-top:14px;
                               font-size:13px;color:#6b7280;
                               font-family:-apple-system,'Segoe UI',Helvetica,Arial,sans-serif;">
                    Accede a tu cuenta en
                    <a href="https://www.marianosevilla.com"
                       style="color:#059669;text-decoration:none;">marianosevilla.com</a>
                  </td>
                </tr>
              </table>
            </td>
          </tr>

          <!-- FOOTER -->
          <tr>
            <td style="padding:18px 4px 40px;">
              <p style="margin:0 0 5px;font-size:11px;color:#9ca3af;line-height:1.7;
                         font-family:-apple-system,'Segoe UI',Helvetica,Arial,sans-serif;">
                Mariano Sevilla &middot; Gestión fiscal de criptomonedas &middot;
                <a href="https://www.marianosevilla.com"
                   style="color:#9ca3af;text-decoration:none;">marianosevilla.com</a>
              </p>
              <p style="margin:0;font-size:11px;color:#9ca3af;line-height:1.7;
                         font-family:-apple-system,'Segoe UI',Helvetica,Arial,sans-serif;">
                Recibes este email porque tienes una cuenta activa. &middot;
                <a href="{unsubscribe_url}"
                   style="color:#9ca3af;text-decoration:underline;">Desuscribirse</a>
                &nbsp;&middot;&nbsp;
                <a href="https://www.marianosevilla.com/privacidad"
                   style="color:#9ca3af;text-decoration:none;">Privacidad</a>
                &nbsp;&middot;&nbsp;
                <a href="https://www.marianosevilla.com/terminos"
                   style="color:#9ca3af;text-decoration:none;">Términos</a>
                &nbsp;&middot;&nbsp;
                <a href="https://www.marianosevilla.com/account"
                   style="color:#9ca3af;text-decoration:none;">Mi cuenta</a>
              </p>
            </td>
          </tr>

        </table>
        <!--[if mso]></td></tr></table><![endif]-->
      </td>
    </tr>
  </table>
</body>
</html>"""


def render_campaign_text(campaign, unsubscribe_url: str = "") -> str:
    """Plain-text fallback — clean prose, no decorations."""
    lines = [
        campaign.subject,
        "=" * min(len(campaign.subject), 60),
        "",
        campaign.body,
        "",
        "--",
        "Mariano Sevilla — Gestión fiscal de criptomonedas",
        "https://www.marianosevilla.com",
    ]
    if unsubscribe_url and unsubscribe_url not in ("#test-email", "#test-no-action"):
        lines += ["", "Para desuscribirte:", unsubscribe_url]
    lines += [
        "",
        "Privacidad: https://www.marianosevilla.com/privacidad",
        "Términos:   https://www.marianosevilla.com/terminos",
        "Mi cuenta:  https://www.marianosevilla.com/account",
    ]
    return "\n".join(lines)
