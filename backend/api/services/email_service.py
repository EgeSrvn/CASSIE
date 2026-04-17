from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage

from backend.api.utils.config_loader import get_config
from backend.api.utils.logger import get_logger

logger = get_logger(__name__)


def email_delivery_enabled() -> bool:
    config = get_config().email
    return config.enabled and bool(config.host and config.from_address)


def send_email(recipient: str, subject: str, text_body: str, html_body: str | None = None) -> bool:
    config = get_config().email
    if not email_delivery_enabled():
        logger.info("Email delivery skipped because SMTP is not configured", extra={"recipient": recipient, "subject": subject})
        return False

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = f"{config.from_name} <{config.from_address}>"
    message["To"] = recipient
    message.set_content(text_body)
    if html_body:
        message.add_alternative(html_body, subtype="html")

    try:
        if config.use_ssl:
            with smtplib.SMTP_SSL(config.host, config.port, context=ssl.create_default_context()) as smtp:
                if config.username:
                    smtp.login(config.username, config.password)
                smtp.send_message(message)
        else:
            with smtplib.SMTP(config.host, config.port) as smtp:
                smtp.ehlo()
                if config.use_tls:
                    smtp.starttls(context=ssl.create_default_context())
                    smtp.ehlo()
                if config.username:
                    smtp.login(config.username, config.password)
                smtp.send_message(message)
        return True
    except Exception as exc:
        logger.error(f"Failed to send email to {recipient}: {exc}", exc_info=True)
        return False
