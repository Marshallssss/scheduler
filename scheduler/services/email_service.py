from __future__ import annotations

from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import logging
import smtplib
import time

from scheduler.config import Settings


class EmailService:
    def __init__(self, settings: Settings, max_retries: int = 3) -> None:
        self.settings = settings
        self.max_retries = max_retries
        self.logger = logging.getLogger(self.__class__.__name__)

    @property
    def configured(self) -> bool:
        return bool(self.settings.smtp_host and self.settings.mail_from)

    def send_email(
        self,
        recipients: list[str],
        subject: str,
        body: str,
        html_body: str | None = None,
    ) -> bool:
        clean_recipients = sorted({item.strip().lower() for item in recipients if item and item.strip()})
        if not clean_recipients:
            self.logger.warning("skip email: empty recipients")
            return False
        if not self.configured:
            self.logger.warning("skip email: smtp not configured")
            return False

        for attempt in range(1, self.max_retries + 1):
            try:
                if html_body is None:
                    self._send_once(clean_recipients, subject, body)
                else:
                    self._send_once(clean_recipients, subject, body, html_body=html_body)
                self.logger.info("email sent subject=%s recipients=%s", subject, ",".join(clean_recipients))
                return True
            except smtplib.SMTPAuthenticationError as exc:
                self.logger.error(
                    "email auth failed err=%s; check smtp_user/smtp_pass and provider SMTP AUTH settings "
                    "(for Outlook/Exchange, Basic AUTH may be disabled and an app password or SMTP AUTH policy is required)",
                    exc,
                )
                return False
            except Exception as exc:  # noqa: BLE001
                self.logger.exception("email send failed attempt=%s err=%s", attempt, exc)
                if attempt == self.max_retries:
                    return False
                time.sleep(2 ** (attempt - 1))
        return False

    def _send_once(
        self,
        recipients: list[str],
        subject: str,
        body: str,
        html_body: str | None = None,
    ) -> None:
        if html_body is None:
            msg = MIMEText(body, "plain", "utf-8")
        else:
            msg = MIMEMultipart("alternative")
            msg.attach(MIMEText(body, "plain", "utf-8"))
            msg.attach(MIMEText(html_body, "html", "utf-8"))
        msg["Subject"] = subject
        msg["From"] = self.settings.mail_from
        msg["To"] = ", ".join(recipients)

        with smtplib.SMTP(self.settings.smtp_host, self.settings.smtp_port, timeout=30) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.ehlo()
            if self.settings.smtp_user:
                smtp.login(self.settings.smtp_user, self.settings.smtp_pass)
            smtp.sendmail(self.settings.mail_from, recipients, msg.as_string())
