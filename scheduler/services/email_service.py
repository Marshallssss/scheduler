from __future__ import annotations

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

    def send_email(self, recipients: list[str], subject: str, body: str) -> bool:
        clean_recipients = sorted({item.strip().lower() for item in recipients if item and item.strip()})
        if not clean_recipients:
            self.logger.warning("skip email: empty recipients")
            return False
        if not self.configured:
            self.logger.warning("skip email: smtp not configured")
            return False

        for attempt in range(1, self.max_retries + 1):
            try:
                self._send_once(clean_recipients, subject, body)
                self.logger.info("email sent subject=%s recipients=%s", subject, ",".join(clean_recipients))
                return True
            except Exception as exc:  # noqa: BLE001
                self.logger.exception("email send failed attempt=%s err=%s", attempt, exc)
                if attempt == self.max_retries:
                    return False
                time.sleep(2 ** (attempt - 1))
        return False

    def _send_once(self, recipients: list[str], subject: str, body: str) -> None:
        msg = MIMEText(body, "plain", "utf-8")
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
