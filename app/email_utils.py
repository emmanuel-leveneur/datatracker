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
