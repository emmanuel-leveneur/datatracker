"""
Utilitaire d'envoi d'emails synchrone (smtplib).
Si SMTP_HOST n'est pas configuré, les appels sont silencieusement ignorés.
"""
import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from app.config import settings

logger = logging.getLogger(__name__)


def send_email(to_addresses: list[str], subject: str, body_text: str) -> None:
    """
    Envoie un email simple (texte brut) à une liste de destinataires.
    Ne lève pas d'exception — les erreurs sont loggées.
    """
    if not settings.SMTP_HOST or not to_addresses:
        return

    from_addr = settings.SMTP_FROM or settings.SMTP_USER
    if not from_addr:
        logger.warning("email_utils: SMTP_FROM et SMTP_USER sont vides, email non envoyé.")
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = ", ".join(to_addresses)
    msg.attach(MIMEText(body_text, "plain", "utf-8"))

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
