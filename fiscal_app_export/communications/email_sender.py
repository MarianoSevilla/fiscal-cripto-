"""
HTML/text template renderer for campaign emails.
Design: premium dark, coherent with Mariano Sevilla branding.
Inline styles only — email client compatibility.
"""
import html as _html


def render_campaign_html(campaign, unsubscribe_url: str) -> str:
    """Renders the full HTML email for a campaign."""
    subject_esc     = _html.escape(campaign.subject)
    body_esc        = _html.escape(campaign.body).replace("\n", "<br>")
    preview_text    = _html.escape(campaign.preview_text or "")
    preview_snippet = (
        f'<div style="display:none;max-height:0;overflow:hidden;mso-hide:all;">'
        f'{preview_text}&nbsp;&#8204;&#8204;&#8204;</div>'
        if preview_text else ""
    )

    return f"""<!DOCTYPE html>
<html lang="es" xmlns:v="urn:schemas-microsoft-com:vml">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta name="color-scheme" content="dark light">
  <meta name="supported-color-schemes" content="dark light">
  <title>{subject_esc}</title>
  <!--[if mso]>
  <noscript><xml><o:OfficeDocumentSettings><o:PixelsPerInch>96</o:PixelsPerInch></o:OfficeDocumentSettings></xml></noscript>
  <![endif]-->
</head>
<body style="margin:0;padding:0;word-break:break-word;background-color:#080c12;-webkit-text-size-adjust:100%;-ms-text-size-adjust:100%;">
  {preview_snippet}
  <table width="100%" cellpadding="0" cellspacing="0" role="presentation"
         style="background-color:#080c12;padding:40px 0;">
    <tr>
      <td align="center" style="padding:0 16px;">
        <!--[if mso]><table width="560"><tr><td><![endif]-->
        <table width="100%" cellpadding="0" cellspacing="0" role="presentation"
               style="max-width:560px;background-color:#10141e;border-radius:12px;
                      border:1px solid rgba(255,255,255,0.07);overflow:hidden;">

          <!-- HEADER -->
          <tr>
            <td style="background-color:#0d1018;padding:24px 40px 22px;
                        border-bottom:1px solid rgba(255,255,255,0.07);">
              <span style="font-size:18px;font-weight:800;color:#eef0f6;
                            font-family:-apple-system,'Segoe UI',Helvetica,Arial,sans-serif;
                            letter-spacing:-0.02em;text-decoration:none;">Mariano</span><span
                style="font-size:18px;font-weight:800;color:#00C896;
                       font-family:-apple-system,'Segoe UI',Helvetica,Arial,sans-serif;">.</span>
            </td>
          </tr>

          <!-- BODY -->
          <tr>
            <td style="padding:36px 40px 32px;background-color:#10141e;">
              <h1 style="margin:0 0 20px;font-size:22px;font-weight:700;
                          color:#f9fafb;line-height:1.35;
                          font-family:-apple-system,'Segoe UI',Helvetica,Arial,sans-serif;">
                {subject_esc}
              </h1>
              <p style="margin:0;font-size:15px;color:#9ca3af;line-height:1.8;
                         font-family:-apple-system,'Segoe UI',Helvetica,Arial,sans-serif;">
                {body_esc}
              </p>
              <table cellpadding="0" cellspacing="0" role="presentation"
                     style="margin:28px 0 0;width:100%;">
                <tr>
                  <td style="border-top:1px solid rgba(255,255,255,0.06);
                               font-size:13px;color:#4b5563;padding-top:16px;
                               font-family:-apple-system,'Segoe UI',Helvetica,Arial,sans-serif;">
                    Accede a tu cuenta en
                    <a href="https://www.marianosevilla.com"
                       style="color:#00C896;text-decoration:none;">marianosevilla.com</a>
                  </td>
                </tr>
              </table>
            </td>
          </tr>

          <!-- FOOTER -->
          <tr>
            <td style="background-color:#0d1018;padding:18px 40px 24px;
                        border-top:1px solid rgba(255,255,255,0.06);">
              <p style="margin:0 0 6px;font-size:11px;color:#4b5563;line-height:1.7;
                         font-family:-apple-system,'Segoe UI',Helvetica,Arial,sans-serif;">
                Mariano Sevilla &middot; Gestión fiscal de criptomonedas<br>
                Estás recibiendo este email porque tienes una cuenta activa en marianosevilla.com.
              </p>
              <p style="margin:8px 0 0;font-size:11px;color:#374151;
                         font-family:-apple-system,'Segoe UI',Helvetica,Arial,sans-serif;">
                Si no deseas recibir futuras actualizaciones, puedes
                <a href="{unsubscribe_url}"
                   style="color:#6b7280;text-decoration:underline;">desuscribirte aquí</a>.
              </p>
              <table cellpadding="0" cellspacing="0" role="presentation"
                     style="margin:12px 0 0;">
                <tr>
                  <td style="padding-right:14px;">
                    <a href="https://www.marianosevilla.com/privacidad"
                       style="font-size:11px;color:#4b5563;text-decoration:none;
                              font-family:-apple-system,'Segoe UI',Helvetica,Arial,sans-serif;">
                      Privacidad
                    </a>
                  </td>
                  <td style="padding-right:14px;">
                    <a href="https://www.marianosevilla.com/terminos"
                       style="font-size:11px;color:#4b5563;text-decoration:none;
                              font-family:-apple-system,'Segoe UI',Helvetica,Arial,sans-serif;">
                      Términos
                    </a>
                  </td>
                  <td>
                    <a href="https://www.marianosevilla.com/account"
                       style="font-size:11px;color:#4b5563;text-decoration:none;
                              font-family:-apple-system,'Segoe UI',Helvetica,Arial,sans-serif;">
                      Mi cuenta
                    </a>
                  </td>
                </tr>
              </table>
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
    """Plain-text fallback for email clients that don't render HTML."""
    lines = [
        campaign.subject,
        "=" * len(campaign.subject),
        "",
        campaign.body,
        "",
        "-" * 40,
        "Mariano Sevilla · Gestión fiscal de criptomonedas",
        "marianosevilla.com",
    ]
    if unsubscribe_url and unsubscribe_url != "#test-email":
        lines += [
            "",
            f"Para desuscribirte de estas comunicaciones visita:",
            unsubscribe_url,
        ]
    return "\n".join(lines)
