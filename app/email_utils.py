"""
Utilitaire d'envoi d'emails synchrone (smtplib).
Si SMTP_HOST n'est pas configuré, les appels sont silencieusement ignorés.
"""
import html
import logging
import smtplib
from datetime import date, datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app.config import settings

logger = logging.getLogger(__name__)


# ── Formatage des valeurs ──────────────────────────────────────────────────────

def _fmt(value: str, col_type_value: str) -> str:
    """Formate une valeur brute selon son type pour l'affichage email."""
    if not value:
        return ""
    if col_type_value == "boolean":
        return "Oui" if value.lower() in ("true", "1", "yes", "oui") else "Non"
    if col_type_value == "date":
        try:
            return date.fromisoformat(value).strftime("%d/%m/%Y")
        except ValueError:
            return value
    if col_type_value == "datetime":
        try:
            return datetime.fromisoformat(value).strftime("%d/%m/%Y %H:%M")
        except ValueError:
            return value
    return value


# ── Construction de la fiche HTML ─────────────────────────────────────────────

def _build_fiche_html(columns, cells: dict, trigger_col_ids: set) -> str:
    """
    Construit le tableau HTML de la fiche ligne.
    - columns : liste ordonnée de TableColumn
    - cells   : {col_id: valeur_brute}
    - trigger_col_ids : col_ids à l'origine du déclenchement (mis en évidence)
    """
    rows_html = []
    for i, col in enumerate(columns):
        raw = cells.get(col.id, "")
        formatted = _fmt(raw, col.col_type.value)
        is_trigger = col.id in trigger_col_ids
        is_empty = not formatted

        # Couleurs alternées + mise en évidence
        if is_trigger:
            row_bg   = "#eff6ff"
            label_style = ("font-size:12px;font-weight:700;color:#1d4ed8;"
                           "padding:9px 14px;width:38%;vertical-align:top;"
                           "border-bottom:1px solid #dbeafe;white-space:nowrap;")
            value_style = ("font-size:13px;color:#1e3a5f;font-weight:600;"
                           "padding:9px 14px;vertical-align:top;"
                           "border-bottom:1px solid #dbeafe;")
            indicator = ('<span style="display:inline-block;width:7px;height:7px;'
                         'background-color:#3b82f6;border-radius:50%;'
                         'margin-right:7px;vertical-align:middle;'
                         'margin-bottom:1px;"></span>')
        else:
            row_bg = "#ffffff" if i % 2 == 0 else "#f9fafb"
            label_style = ("font-size:12px;font-weight:600;color:#6b7280;"
                           "padding:8px 14px;width:38%;vertical-align:top;"
                           "border-bottom:1px solid #f3f4f6;white-space:nowrap;")
            value_style = ("font-size:13px;color:#111827;"
                           "padding:8px 14px;vertical-align:top;"
                           "border-bottom:1px solid #f3f4f6;")
            indicator = ""

        if is_empty:
            value_html = '<span style="color:#d1d5db;font-style:italic;">—</span>'
        else:
            value_html = html.escape(formatted)

        rows_html.append(
            f'<tr style="background-color:{row_bg};">'
            f'<td style="{label_style}">'
            f'{indicator}{html.escape(col.name)}'
            f'</td>'
            f'<td style="{value_style}">{value_html}</td>'
            f'</tr>'
        )

    return "\n".join(rows_html)


# ── Template principal ─────────────────────────────────────────────────────────

_HEADER = """\
<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{subject}</title>
</head>
<body style="margin:0;padding:0;background-color:#f3f4f6;
             font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,
             'Helvetica Neue',Arial,sans-serif;">

<table width="100%" cellpadding="0" cellspacing="0" role="presentation"
       style="background-color:#f3f4f6;min-height:100vh;">
  <tr>
    <td align="center" style="padding:40px 16px;">
      <table width="100%" cellpadding="0" cellspacing="0" role="presentation"
             style="max-width:600px;">

        <!-- Header -->
        <tr>
          <td style="background-color:#1d4ed8;border-radius:12px 12px 0 0;
                      padding:22px 32px;">
            <table width="100%" cellpadding="0" cellspacing="0" role="presentation">
              <tr>
                <td>
                  <span style="color:#ffffff;font-size:20px;font-weight:700;
                               letter-spacing:0.3px;">DataTracker</span>
                </td>
                <td align="right">
                  <span style="display:inline-block;background-color:#1e40af;
                               color:#bfdbfe;font-size:11px;font-weight:600;
                               padding:3px 10px;border-radius:20px;
                               letter-spacing:0.4px;text-transform:uppercase;">
                    Alerte
                  </span>
                </td>
              </tr>
            </table>
          </td>
        </tr>

        <!-- Bande colorée -->
        <tr>
          <td style="height:4px;background:linear-gradient(90deg,#3b82f6,#60a5fa);"></td>
        </tr>

        <!-- Corps -->
        <tr>
          <td style="background-color:#ffffff;padding:28px 32px 24px 32px;">

            <!-- Badge déclenchement -->
            <table cellpadding="0" cellspacing="0" role="presentation"
                   style="margin-bottom:18px;">
              <tr>
                <td style="background-color:#eff6ff;border:1px solid #bfdbfe;
                            border-radius:8px;padding:9px 16px;">
                  <table cellpadding="0" cellspacing="0" role="presentation">
                    <tr>
                      <td style="padding-right:10px;font-size:18px;
                                 vertical-align:middle;">🔔</td>
                      <td style="vertical-align:middle;">
                        <span style="font-size:12px;font-weight:700;color:#1d4ed8;
                                     text-transform:uppercase;letter-spacing:0.5px;">
                          Condition déclenchée
                        </span>
                      </td>
                    </tr>
                  </table>
                </td>
              </tr>
            </table>

            <!-- Nom alerte + table -->
            <h1 style="margin:0 0 4px 0;font-size:21px;font-weight:700;
                        color:#111827;line-height:1.3;">{alert_name}</h1>
            <p style="margin:0 0 20px 0;font-size:13px;color:#6b7280;">
              <span style="color:#374151;font-weight:600;">{table_name}</span>
              &nbsp;·&nbsp;Ligne&nbsp;
              <span style="color:#374151;font-weight:600;">#{row_id}</span>
            </p>

            <!-- Résumé de la condition -->
            <div style="background-color:#f9fafb;border:1px solid #e5e7eb;
                         border-left:4px solid #3b82f6;border-radius:0 6px 6px 0;
                         padding:12px 16px;margin-bottom:24px;">
              <p style="margin:0;font-size:13px;color:#374151;line-height:1.7;">
                {message}
              </p>
            </div>

            <!-- Titre fiche -->
            <p style="margin:0 0 8px 0;font-size:11px;font-weight:700;
                       color:#9ca3af;text-transform:uppercase;letter-spacing:0.7px;">
              Données de la ligne
            </p>
"""

_FICHE_WRAPPER = """\
            <!-- Fiche ligne -->
            <div style="border:1px solid #e5e7eb;border-radius:8px;
                         overflow:hidden;margin-bottom:28px;">
              <table width="100%" cellpadding="0" cellspacing="0"
                     style="border-collapse:collapse;">
{fiche_rows}
              </table>
            </div>

            <!-- Note mise en évidence -->
            <p style="margin:0 0 24px 0;font-size:11px;color:#9ca3af;line-height:1.5;">
              <span style="display:inline-block;width:7px;height:7px;
                           background-color:#3b82f6;border-radius:50%;
                           margin-right:5px;vertical-align:middle;"></span>
              Champs à l'origine du déclenchement de l'alerte
            </p>
"""

_FOOTER = """\
            <!-- Bouton CTA -->
            <table cellpadding="0" cellspacing="0" role="presentation">
              <tr>
                <td style="border-radius:8px;background-color:#2563eb;">
                  <a href="{table_url}"
                     style="display:inline-block;padding:12px 28px;
                            font-size:14px;font-weight:600;color:#ffffff;
                            text-decoration:none;letter-spacing:0.2px;">
                    Voir le tableau &nbsp;→
                  </a>
                </td>
              </tr>
            </table>

          </td>
        </tr>

        <!-- Footer -->
        <tr>
          <td style="background-color:#f9fafb;border-top:1px solid #e5e7eb;
                      border-radius:0 0 12px 12px;padding:16px 32px;">
            <p style="margin:0;font-size:12px;color:#9ca3af;text-align:center;
                       line-height:1.6;">
              Notification automatique de&nbsp;
              <strong style="color:#6b7280;">DataTracker</strong>
              &nbsp;·&nbsp;Ne pas répondre à cet email
            </p>
          </td>
        </tr>

      </table>
    </td>
  </tr>
</table>
</body>
</html>
"""

_TEXT_TEMPLATE = """\
[DataTracker] {table_name} — {alert_name}
Ligne #{row_id}

{message}

── Données de la ligne ──────────────────
{fiche_text}
─────────────────────────────────────────

Voir le tableau : {table_url}

Notification automatique de DataTracker. Ne pas répondre à cet email.
"""

_SHARE_HTML = """\
<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{subject}</title>
</head>
<body style="margin:0;padding:0;background-color:#f3f4f6;
             font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,
             'Helvetica Neue',Arial,sans-serif;">

<table width="100%" cellpadding="0" cellspacing="0" role="presentation"
       style="background-color:#f3f4f6;min-height:100vh;">
  <tr>
    <td align="center" style="padding:40px 16px;">
      <table width="100%" cellpadding="0" cellspacing="0" role="presentation"
             style="max-width:600px;">

        <!-- Header -->
        <tr>
          <td style="background-color:#1d4ed8;border-radius:12px 12px 0 0;
                      padding:22px 32px;">
            <table width="100%" cellpadding="0" cellspacing="0" role="presentation">
              <tr>
                <td>
                  <span style="color:#ffffff;font-size:20px;font-weight:700;
                               letter-spacing:0.3px;">DataTracker</span>
                </td>
                <td align="right">
                  <span style="display:inline-block;background-color:#065f46;
                               color:#a7f3d0;font-size:11px;font-weight:600;
                               padding:3px 10px;border-radius:20px;
                               letter-spacing:0.4px;text-transform:uppercase;">
                    Partage
                  </span>
                </td>
              </tr>
            </table>
          </td>
        </tr>

        <!-- Bande colorée -->
        <tr>
          <td style="height:4px;background:linear-gradient(90deg,#10b981,#34d399);"></td>
        </tr>

        <!-- Corps -->
        <tr>
          <td style="background-color:#ffffff;padding:28px 32px 24px 32px;">

            <!-- Badge partage -->
            <table cellpadding="0" cellspacing="0" role="presentation"
                   style="margin-bottom:18px;">
              <tr>
                <td style="background-color:#ecfdf5;border:1px solid #a7f3d0;
                            border-radius:8px;padding:9px 16px;">
                  <table cellpadding="0" cellspacing="0" role="presentation">
                    <tr>
                      <td style="padding-right:10px;font-size:18px;
                                 vertical-align:middle;">&#128279;</td>
                      <td style="vertical-align:middle;">
                        <span style="font-size:12px;font-weight:700;color:#065f46;
                                     text-transform:uppercase;letter-spacing:0.5px;">
                          Table partagée avec vous
                        </span>
                      </td>
                    </tr>
                  </table>
                </td>
              </tr>
            </table>

            <!-- Nom table -->
            <h1 style="margin:0 0 20px 0;font-size:21px;font-weight:700;
                        color:#111827;line-height:1.3;">{table_name}</h1>

            <!-- Détails partage -->
            <div style="border:1px solid #e5e7eb;border-radius:8px;overflow:hidden;
                         margin-bottom:28px;">
              <table width="100%" cellpadding="0" cellspacing="0"
                     style="border-collapse:collapse;">
                <tr style="background-color:#f9fafb;">
                  <td style="font-size:12px;font-weight:600;color:#6b7280;
                              padding:9px 14px;width:38%;border-bottom:1px solid #f3f4f6;
                              white-space:nowrap;">Partagé par</td>
                  <td style="font-size:13px;color:#111827;
                              padding:9px 14px;border-bottom:1px solid #f3f4f6;">
                    {shared_by}
                  </td>
                </tr>
                <tr style="background-color:#ffffff;">
                  <td style="font-size:12px;font-weight:600;color:#6b7280;
                              padding:9px 14px;width:38%;white-space:nowrap;">
                    Niveau d'accès
                  </td>
                  <td style="font-size:13px;color:#111827;padding:9px 14px;">
                    {level_label}
                  </td>
                </tr>
              </table>
            </div>

            <!-- Bouton CTA -->
            <table cellpadding="0" cellspacing="0" role="presentation">
              <tr>
                <td style="border-radius:8px;background-color:#2563eb;">
                  <a href="{table_url}"
                     style="display:inline-block;padding:12px 28px;
                            font-size:14px;font-weight:600;color:#ffffff;
                            text-decoration:none;letter-spacing:0.2px;">
                    Voir le tableau &nbsp;&#8594;
                  </a>
                </td>
              </tr>
            </table>

          </td>
        </tr>

        <!-- Footer -->
        <tr>
          <td style="background-color:#f9fafb;border-top:1px solid #e5e7eb;
                      border-radius:0 0 12px 12px;padding:16px 32px;">
            <p style="margin:0;font-size:12px;color:#9ca3af;text-align:center;
                       line-height:1.6;">
              Notification automatique de&nbsp;
              <strong style="color:#6b7280;">DataTracker</strong>
              &nbsp;&#183;&nbsp;Ne pas répondre à cet email
            </p>
          </td>
        </tr>

      </table>
    </td>
  </tr>
</table>
</body>
</html>
"""

_SHARE_TEXT_TEMPLATE = """\
[DataTracker] Table partagée avec vous : {table_name}

{shared_by} vous a accordé l'accès à la table "{table_name}".
Niveau d'accès : {level_label}

Voir le tableau : {table_url}

Notification automatique de DataTracker. Ne pas répondre à cet email.
"""

_CONFIRM_HTML = """\
<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Confirmez votre adresse email — DataTracker</title>
</head>
<body style="margin:0;padding:0;background-color:#f3f4f6;
             font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,
             'Helvetica Neue',Arial,sans-serif;">

<table width="100%" cellpadding="0" cellspacing="0" role="presentation"
       style="background-color:#f3f4f6;min-height:100vh;">
  <tr>
    <td align="center" style="padding:40px 16px;">
      <table width="100%" cellpadding="0" cellspacing="0" role="presentation"
             style="max-width:600px;">

        <!-- Header -->
        <tr>
          <td style="background-color:#1d4ed8;border-radius:12px 12px 0 0;
                      padding:22px 32px;">
            <table width="100%" cellpadding="0" cellspacing="0" role="presentation">
              <tr>
                <td>
                  <span style="color:#ffffff;font-size:20px;font-weight:700;
                               letter-spacing:0.3px;">DataTracker</span>
                </td>
                <td align="right">
                  <span style="display:inline-block;background-color:#1e40af;
                               color:#bfdbfe;font-size:11px;font-weight:600;
                               padding:3px 10px;border-radius:20px;
                               letter-spacing:0.4px;text-transform:uppercase;">
                    Confirmation
                  </span>
                </td>
              </tr>
            </table>
          </td>
        </tr>

        <!-- Bande colorée -->
        <tr>
          <td style="height:4px;background:linear-gradient(90deg,#3b82f6,#60a5fa);"></td>
        </tr>

        <!-- Corps -->
        <tr>
          <td style="background-color:#ffffff;padding:28px 32px 24px 32px;">

            <h1 style="margin:0 0 12px 0;font-size:21px;font-weight:700;
                        color:#111827;line-height:1.3;">
              Confirmez votre adresse email
            </h1>

            <p style="margin:0 0 24px 0;font-size:14px;color:#374151;line-height:1.6;">
              Bonjour <strong>{username}</strong>,<br>
              Cliquez sur le bouton ci-dessous pour activer votre compte DataTracker.
            </p>

            <!-- Bouton CTA -->
            <table cellpadding="0" cellspacing="0" role="presentation"
                   style="margin-bottom:24px;">
              <tr>
                <td style="border-radius:8px;background-color:#2563eb;">
                  <a href="{confirmation_url}"
                     style="display:inline-block;padding:12px 28px;
                            font-size:14px;font-weight:600;color:#ffffff;
                            text-decoration:none;letter-spacing:0.2px;">
                    Confirmer mon adresse email &nbsp;&#8594;
                  </a>
                </td>
              </tr>
            </table>

            <p style="margin:0;font-size:12px;color:#9ca3af;line-height:1.5;">
              Ce lien expire dans <strong style="color:#6b7280;">10&nbsp;minutes</strong>.
              Si vous n'avez pas créé de compte, ignorez cet email.
            </p>

          </td>
        </tr>

        <!-- Footer -->
        <tr>
          <td style="background-color:#f9fafb;border-top:1px solid #e5e7eb;
                      border-radius:0 0 12px 12px;padding:16px 32px;">
            <p style="margin:0;font-size:12px;color:#9ca3af;text-align:center;
                       line-height:1.6;">
              Notification automatique de&nbsp;
              <strong style="color:#6b7280;">DataTracker</strong>
              &nbsp;&#183;&nbsp;Ne pas répondre à cet email
            </p>
          </td>
        </tr>

      </table>
    </td>
  </tr>
</table>
</body>
</html>
"""

_CONFIRM_TEXT_TEMPLATE = """\
[DataTracker] Confirmez votre adresse email

Bonjour {username},

Cliquez sur le lien ci-dessous pour activer votre compte DataTracker.
Ce lien expire dans 10 minutes.

{confirmation_url}

Si vous n'avez pas créé de compte, ignorez cet email.
Notification automatique de DataTracker. Ne pas répondre à cet email.
"""


# ── Fonction publique ──────────────────────────────────────────────────────────

def send_alert_email(
    to_addresses: list[str],
    alert_name: str,
    table_name: str,
    table_id: int,
    row_id: int,
    message: str,
    columns=None,
    cells: dict | None = None,
    trigger_col_ids: set | None = None,
) -> None:
    """
    Envoie un email HTML pour une notification d'alerte.
    - columns       : liste ordonnée de TableColumn (pour la fiche ligne)
    - cells         : {col_id: valeur_brute}
    - trigger_col_ids : col_ids des colonnes ayant déclenché l'alerte
    Ne lève pas d'exception — les erreurs sont loggées.
    """
    if not settings.SMTP_HOST or not to_addresses:
        return

    from_addr = settings.SMTP_FROM or settings.SMTP_USER
    if not from_addr:
        logger.warning("email_utils: SMTP_FROM et SMTP_USER sont vides, email non envoyé.")
        return

    table_url = f"{settings.APP_URL.rstrip('/')}/tables/{table_id}"
    subject = f"{table_name} — {alert_name}"

    # ── Fiche HTML ──
    if columns and cells is not None:
        fiche_rows = _build_fiche_html(columns, cells, trigger_col_ids or set())
        fiche_section = _FICHE_WRAPPER.format(fiche_rows=fiche_rows)

        # Fiche texte brut
        fiche_text_lines = []
        for col in columns:
            raw = cells.get(col.id, "")
            formatted = _fmt(raw, col.col_type.value) or "—"
            mark = " ◀" if col.id in (trigger_col_ids or set()) else ""
            fiche_text_lines.append(f"  {col.name} : {formatted}{mark}")
        fiche_text = "\n".join(fiche_text_lines)
    else:
        fiche_section = ""
        fiche_text = ""

    html_body = (
        _HEADER.format(
            subject=html.escape(subject),
            alert_name=html.escape(alert_name),
            table_name=html.escape(table_name),
            row_id=row_id,
            message=html.escape(message),
        )
        + fiche_section
        + _FOOTER.format(table_url=table_url)
    )

    text_body = _TEXT_TEMPLATE.format(
        table_name=table_name,
        alert_name=alert_name,
        row_id=row_id,
        message=message,
        fiche_text=fiche_text,
        table_url=table_url,
    )

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = ", ".join(to_addresses)
    msg.attach(MIMEText(text_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        if settings.SMTP_USE_TLS:
            server = smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=10)
            server.ehlo()
            server.starttls()
            server.ehlo()
        else:
            server = smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=10)

        if settings.SMTP_USER and settings.SMTP_PASSWORD:
            server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)

        server.sendmail(from_addr, to_addresses, msg.as_string())
        server.quit()
        logger.info("email_utils: email envoyé à %s — %s", to_addresses, subject)
    except Exception as exc:
        logger.error("email_utils: échec envoi email — %s", exc)


def _build_bulk_rows_table_html(columns, rows: list[dict]) -> tuple[str, str]:
    """
    Construit l'en-tête et le corps d'un tableau HTML multi-lignes pour le partage en
    masse. `rows` est une liste de {col_id: valeur_brute}, une entrée par ligne, dans
    l'ordre d'affichage voulu.
    Retourne (header_html, body_html).
    """
    th_style = (
        "font-size:11px;font-weight:700;color:#065f46;text-transform:uppercase;"
        "letter-spacing:0.4px;padding:9px 12px;text-align:left;white-space:nowrap;"
        "border-bottom:2px solid #a7f3d0;"
    )
    header_html = "".join(
        f'<th style="{th_style}">{html.escape(col.name)}</th>' for col in columns
    )

    td_style = (
        "font-size:12.5px;color:#111827;padding:8px 12px;"
        "border-bottom:1px solid #f3f4f6;vertical-align:top;"
    )
    body_rows = []
    for i, cells in enumerate(rows):
        bg = "#ffffff" if i % 2 == 0 else "#f9fafb"
        tds = []
        for col in columns:
            formatted = _fmt(cells.get(col.id, ""), col.col_type.value)
            value_html = (
                html.escape(formatted) if formatted
                else '<span style="color:#d1d5db;font-style:italic;">—</span>'
            )
            tds.append(f'<td style="{td_style}">{value_html}</td>')
        body_rows.append(f'<tr style="background-color:{bg};">{"".join(tds)}</tr>')
    return header_html, "\n".join(body_rows)


# ── Template partage (ligne unique / en masse) ─────────────────────────────────

_SHARE_ROW_HEADER = """\
<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{subject}</title>
</head>
<body style="margin:0;padding:0;background-color:#f3f4f6;
             font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,
             'Helvetica Neue',Arial,sans-serif;">

<table width="100%" cellpadding="0" cellspacing="0" role="presentation"
       style="background-color:#f3f4f6;min-height:100vh;">
  <tr>
    <td align="center" style="padding:40px 16px;">
      <table width="100%" cellpadding="0" cellspacing="0" role="presentation"
             style="max-width:{max_width}px;">

        <!-- Header -->
        <tr>
          <td style="background-color:#1d4ed8;border-radius:12px 12px 0 0;
                      padding:22px 32px;">
            <table width="100%" cellpadding="0" cellspacing="0" role="presentation">
              <tr>
                <td>
                  <span style="color:#ffffff;font-size:20px;font-weight:700;
                               letter-spacing:0.3px;">DataTracker</span>
                </td>
                <td align="right">
                  <span style="display:inline-block;background-color:#065f46;
                               color:#a7f3d0;font-size:11px;font-weight:600;
                               padding:3px 10px;border-radius:20px;
                               letter-spacing:0.4px;text-transform:uppercase;">
                    Partage
                  </span>
                </td>
              </tr>
            </table>
          </td>
        </tr>

        <!-- Bande colorée -->
        <tr>
          <td style="height:4px;background:linear-gradient(90deg,#10b981,#34d399);"></td>
        </tr>

        <!-- Corps -->
        <tr>
          <td style="background-color:#ffffff;padding:28px 32px 24px 32px;">

            <h1 style="margin:0 0 4px 0;font-size:21px;font-weight:700;
                        color:#111827;line-height:1.3;">{table_name}</h1>
            <p style="margin:0 0 20px 0;font-size:13px;color:#6b7280;">
              Partagé par&nbsp;<span style="color:#374151;font-weight:600;">{shared_by}</span>
              &nbsp;·&nbsp;{scope_label}
            </p>
"""

_SHARE_MESSAGE_BLOCK = """\
            <div style="background-color:#f9fafb;border:1px solid #e5e7eb;
                         border-left:4px solid #10b981;border-radius:0 6px 6px 0;
                         padding:12px 16px;margin-bottom:24px;">
              <p style="margin:0;font-size:13px;color:#374151;line-height:1.7;
                         white-space:pre-wrap;">{message}</p>
            </div>
"""

_SHARE_SECTION_TITLE = """\
            <p style="margin:0 0 8px 0;font-size:11px;font-weight:700;
                       color:#9ca3af;text-transform:uppercase;letter-spacing:0.7px;">
              {section_title}
            </p>
"""

_SHARE_ROW_FICHE_WRAPPER = """\
            <div style="border:1px solid #e5e7eb;border-radius:8px;
                         overflow:hidden;margin-bottom:28px;">
              <table width="100%" cellpadding="0" cellspacing="0"
                     style="border-collapse:collapse;">
{fiche_rows}
              </table>
            </div>
"""

_SHARE_BULK_TABLE_WRAPPER = """\
            <div style="border:1px solid #e5e7eb;border-radius:8px;
                         overflow:auto;margin-bottom:28px;">
              <table width="100%" cellpadding="0" cellspacing="0"
                     style="border-collapse:collapse;">
                <tr style="background-color:#ecfdf5;">{table_header}</tr>
{table_body}
              </table>
            </div>
"""

_SHARE_FOOTER = """\
            <table cellpadding="0" cellspacing="0" role="presentation">
              <tr>
                <td style="border-radius:8px;background-color:#2563eb;">
                  <a href="{table_url}"
                     style="display:inline-block;padding:12px 28px;
                            font-size:14px;font-weight:600;color:#ffffff;
                            text-decoration:none;letter-spacing:0.2px;">
                    Voir le tableau &nbsp;→
                  </a>
                </td>
              </tr>
            </table>

          </td>
        </tr>

        <!-- Footer -->
        <tr>
          <td style="background-color:#f9fafb;border-top:1px solid #e5e7eb;
                      border-radius:0 0 12px 12px;padding:16px 32px;">
            <p style="margin:0;font-size:12px;color:#9ca3af;text-align:center;
                       line-height:1.6;">
              Email envoyé via&nbsp;
              <strong style="color:#6b7280;">DataTracker</strong>
              &nbsp;·&nbsp;par {shared_by}
            </p>
          </td>
        </tr>

      </table>
    </td>
  </tr>
</table>
</body>
</html>
"""

_SHARE_ROW_TEXT_TEMPLATE = """\
[DataTracker] {table_name} — partagé par {shared_by}
Ligne #{row_id}

{message}

── Données de la ligne ──────────────────
{fiche_text}
─────────────────────────────────────────

Voir le tableau : {table_url}

Email envoyé via DataTracker par {shared_by}.
"""

_SHARE_BULK_TEXT_TEMPLATE = """\
[DataTracker] {table_name} — {row_count} ligne(s) partagée(s) par {shared_by}

{message}

── Données partagées ────────────────────
{rows_text}
─────────────────────────────────────────

Voir le tableau : {table_url}

Email envoyé via DataTracker par {shared_by}.
"""


def build_row_share_eml(
    to_addresses: list[str],
    from_address: str,
    shared_by: str,
    table_name: str,
    table_id: int,
    row_id: int,
    message: str,
    columns,
    cells: dict,
) -> bytes:
    """
    Construit (sans l'envoyer) le message MIME (.eml) de partage d'une ligne : fiche
    complète + texte libre, destinataires/objet pré-remplis. L'email n'est jamais
    envoyé par DataTracker — le fichier est téléchargé puis ouvert/édité/envoyé par
    l'utilisateur depuis son propre client mail (ne dépend donc pas de SMTP_HOST).
    Retourne les octets bruts du message (RFC 822), prêts à être servis en téléchargement.
    """
    table_url = f"{settings.APP_URL.rstrip('/')}/tables/{table_id}"
    subject = f"{table_name} — partagé par {shared_by}"

    fiche_rows = _build_fiche_html(columns, cells, set())
    fiche_section = (
        _SHARE_SECTION_TITLE.format(section_title="Données de la ligne")
        + _SHARE_ROW_FICHE_WRAPPER.format(fiche_rows=fiche_rows)
    )

    fiche_text_lines = []
    for col in columns:
        formatted = _fmt(cells.get(col.id, ""), col.col_type.value) or "—"
        fiche_text_lines.append(f"  {col.name} : {formatted}")
    fiche_text = "\n".join(fiche_text_lines)

    html_body = (
        _SHARE_ROW_HEADER.format(
            subject=html.escape(subject), max_width=600,
            table_name=html.escape(table_name),
            shared_by=html.escape(shared_by),
            scope_label=f"Ligne&nbsp;#{row_id}",
        )
        + _SHARE_MESSAGE_BLOCK.format(message=html.escape(message))
        + fiche_section
        + _SHARE_FOOTER.format(table_url=table_url, shared_by=html.escape(shared_by))
    )

    text_body = _SHARE_ROW_TEXT_TEMPLATE.format(
        table_name=table_name, shared_by=shared_by, row_id=row_id,
        message=message, fiche_text=fiche_text, table_url=table_url,
    )

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_address
    msg["To"] = ", ".join(to_addresses)
    msg.attach(MIMEText(text_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    return msg.as_bytes()


def build_bulk_rows_share_eml(
    to_addresses: list[str],
    from_address: str,
    shared_by: str,
    table_name: str,
    table_id: int,
    row_count: int,
    message: str,
    columns,
    rows: list[dict],
) -> bytes:
    """
    Construit (sans l'envoyer) le message MIME (.eml) de partage de plusieurs lignes :
    tableau HTML des colonnes choisies + texte libre, destinataires/objet pré-remplis.
    - rows : liste de {col_id: valeur_brute}, une entrée par ligne partagée.
    Même logique que build_row_share_eml() — jamais envoyé par DataTracker.
    Retourne les octets bruts du message (RFC 822).
    """
    table_url = f"{settings.APP_URL.rstrip('/')}/tables/{table_id}"
    row_label = "ligne" if row_count == 1 else "lignes"
    subject = f"{table_name} — {row_count} {row_label} partagée(s) par {shared_by}"

    table_header, table_body = _build_bulk_rows_table_html(columns, rows)
    table_section = (
        _SHARE_SECTION_TITLE.format(section_title=f"Données partagées ({row_count} {row_label})")
        + _SHARE_BULK_TABLE_WRAPPER.format(table_header=table_header, table_body=table_body)
    )

    rows_text_blocks = []
    for i, cells in enumerate(rows, start=1):
        lines = [f"Ligne {i}/{row_count} :"]
        for col in columns:
            formatted = _fmt(cells.get(col.id, ""), col.col_type.value) or "—"
            lines.append(f"  {col.name} : {formatted}")
        rows_text_blocks.append("\n".join(lines))
    rows_text = "\n\n".join(rows_text_blocks)

    html_body = (
        _SHARE_ROW_HEADER.format(
            subject=html.escape(subject), max_width=720,
            table_name=html.escape(table_name),
            shared_by=html.escape(shared_by),
            scope_label=f"{row_count}&nbsp;{row_label}",
        )
        + _SHARE_MESSAGE_BLOCK.format(message=html.escape(message))
        + table_section
        + _SHARE_FOOTER.format(table_url=table_url, shared_by=html.escape(shared_by))
    )

    text_body = _SHARE_BULK_TEXT_TEMPLATE.format(
        table_name=table_name, row_count=row_count, shared_by=shared_by,
        message=message, rows_text=rows_text, table_url=table_url,
    )

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_address
    msg["To"] = ", ".join(to_addresses)
    msg.attach(MIMEText(text_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    return msg.as_bytes()


def send_share_notification_email(
    to_address: str,
    table_name: str,
    table_id: int,
    permission_level: str,
    shared_by_username: str,
) -> None:
    """
    Envoie un email de notification lorsqu'une table est partagée avec un utilisateur.
    - permission_level : valeur brute du PermissionLevel ("read" ou "write")
    Ne lève pas d'exception — les erreurs sont loggées.
    """
    if not settings.SMTP_HOST or not to_address:
        return

    from_addr = settings.SMTP_FROM or settings.SMTP_USER
    if not from_addr:
        logger.warning("email_utils: SMTP_FROM et SMTP_USER sont vides, email non envoyé.")
        return

    table_url = f"{settings.APP_URL.rstrip('/')}/tables/{table_id}"
    level_label = "Lecture seule" if permission_level == "read" else "Lecture et écriture"
    subject = f"Table partagée avec vous : {table_name}"

    html_body = _SHARE_HTML.format(
        subject=html.escape(subject),
        table_name=html.escape(table_name),
        shared_by=html.escape(shared_by_username),
        level_label=html.escape(level_label),
        table_url=table_url,
    )

    text_body = _SHARE_TEXT_TEMPLATE.format(
        table_name=table_name,
        shared_by=shared_by_username,
        level_label=level_label,
        table_url=table_url,
    )

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to_address
    msg.attach(MIMEText(text_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        if settings.SMTP_USE_TLS:
            server = smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=10)
            server.ehlo()
            server.starttls()
            server.ehlo()
        else:
            server = smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=10)

        if settings.SMTP_USER and settings.SMTP_PASSWORD:
            server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)

        server.sendmail(from_addr, [to_address], msg.as_string())
        server.quit()
        logger.info("email_utils: email partage envoyé à %s — %s", to_address, subject)
    except Exception as exc:
        logger.error("email_utils: échec envoi email partage — %s", exc)


def send_confirmation_email(
    to_address: str,
    username: str,
    confirmation_url: str,
) -> None:
    """
    Envoie l'email de confirmation d'adresse email lors de l'inscription.
    Ne lève pas d'exception — les erreurs sont loggées.
    """
    if not settings.SMTP_HOST or not to_address:
        return

    from_addr = settings.SMTP_FROM or settings.SMTP_USER
    if not from_addr:
        logger.warning("email_utils: SMTP_FROM et SMTP_USER sont vides, email non envoyé.")
        return

    subject = "Confirmez votre adresse email — DataTracker"

    html_body = _CONFIRM_HTML.format(
        username=html.escape(username),
        confirmation_url=confirmation_url,
    )

    text_body = _CONFIRM_TEXT_TEMPLATE.format(
        username=username,
        confirmation_url=confirmation_url,
    )

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to_address
    msg.attach(MIMEText(text_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        if settings.SMTP_USE_TLS:
            server = smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=10)
            server.ehlo()
            server.starttls()
            server.ehlo()
        else:
            server = smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=10)

        if settings.SMTP_USER and settings.SMTP_PASSWORD:
            server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)

        server.sendmail(from_addr, [to_address], msg.as_string())
        server.quit()
        logger.info("email_utils: email confirmation envoyé à %s", to_address)
    except Exception as exc:
        logger.error("email_utils: échec envoi email confirmation — %s", exc)


_RESET_HTML = """\
<!DOCTYPE html>
<html lang="fr">
<body style="font-family:sans-serif;background:#f3f4f6;padding:32px">
  <div style="max-width:520px;margin:auto;background:#fff;border-radius:12px;padding:32px;border:1px solid #e5e7eb">
    <h2 style="color:#1e40af;margin-top:0">Réinitialisation de mot de passe</h2>
    <p>Bonjour <strong>{username}</strong>,</p>
    <p>Vous avez demandé la réinitialisation de votre mot de passe DataTracker.</p>
    <p>Cliquez sur le bouton ci-dessous pour choisir un nouveau mot de passe. Ce lien est valable <strong>30 minutes</strong>.</p>
    <p style="text-align:center;margin:32px 0">
      <a href="{reset_url}"
         style="background:#2563eb;color:#fff;padding:12px 28px;border-radius:8px;text-decoration:none;font-weight:600;display:inline-block">
        Réinitialiser mon mot de passe
      </a>
    </p>
    <p style="font-size:13px;color:#6b7280">Si vous n'êtes pas à l'origine de cette demande, ignorez cet email. Votre mot de passe ne sera pas modifié.</p>
    <hr style="border:none;border-top:1px solid #e5e7eb;margin:24px 0">
    <p style="font-size:12px;color:#9ca3af;text-align:center">DataTracker</p>
  </div>
</body>
</html>
"""

_RESET_TEXT = """\
Réinitialisation de mot de passe — DataTracker

Bonjour {username},

Vous avez demandé la réinitialisation de votre mot de passe DataTracker.

Cliquez sur le lien ci-dessous (valable 30 minutes) :
{reset_url}

Si vous n'êtes pas à l'origine de cette demande, ignorez cet email.
"""


def send_password_reset_email(to_address: str, username: str, reset_url: str) -> None:
    """Envoie le lien de réinitialisation de mot de passe. Ne lève pas d'exception."""
    if not settings.SMTP_HOST or not to_address:
        logger.info("email_utils: SMTP non configuré — lien de reset : %s", reset_url)
        return

    from_addr = settings.SMTP_FROM or settings.SMTP_USER
    if not from_addr:
        logger.warning("email_utils: SMTP_FROM et SMTP_USER vides, reset email non envoyé.")
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = "Réinitialisation de mot de passe — DataTracker"
    msg["From"] = from_addr
    msg["To"] = to_address
    msg.attach(MIMEText(_RESET_TEXT.format(username=username, reset_url=reset_url), "plain", "utf-8"))
    msg.attach(MIMEText(_RESET_HTML.format(username=html.escape(username), reset_url=reset_url), "html", "utf-8"))

    try:
        if settings.SMTP_USE_TLS:
            server = smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=10)
            server.ehlo()
            server.starttls()
            server.ehlo()
        else:
            server = smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=10)
        if settings.SMTP_USER and settings.SMTP_PASSWORD:
            server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
        server.sendmail(from_addr, [to_address], msg.as_string())
        server.quit()
        logger.info("email_utils: email reset envoyé à %s", to_address)
    except Exception as exc:
        logger.error("email_utils: échec envoi email reset — %s", exc)
