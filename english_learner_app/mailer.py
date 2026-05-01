from __future__ import annotations

import smtplib
from email.message import EmailMessage

from .config import AppConfig


class Mailer:
    def __init__(self, config: AppConfig) -> None:
        self.config = config

    def send_otp(self, *, email: str, otp: str, full_name: str) -> dict[str, str]:
        if not self.config.smtp_host or not self.config.smtp_sender:
            print(
                f"[dev-mailer] OTP for {email} ({full_name}) is {otp}. "
                "Configure SMTP_* variables to send real mail."
            )
            return {"mode": "console"}

        message = EmailMessage()
        message["Subject"] = f"{self.config.app_name} verification code"
        message["From"] = self.config.smtp_sender
        message["To"] = email
        message.set_content(
            "\n".join(
                [
                    f"Hi {full_name},",
                    "",
                    f"Your verification code is: {otp}",
                    "",
                    "This code expires soon. If you did not request this account, you can ignore this email.",
                ]
            )
        )

        if self.config.smtp_use_ssl:
            with smtplib.SMTP_SSL(
                self.config.smtp_host, self.config.smtp_port, timeout=20
            ) as client:
                if self.config.smtp_username and self.config.smtp_password:
                    client.login(self.config.smtp_username, self.config.smtp_password)
                client.send_message(message)
        else:
            with smtplib.SMTP(
                self.config.smtp_host, self.config.smtp_port, timeout=20
            ) as client:
                if self.config.smtp_use_starttls:
                    client.starttls()
                if self.config.smtp_username and self.config.smtp_password:
                    client.login(self.config.smtp_username, self.config.smtp_password)
                client.send_message(message)

        return {"mode": "smtp"}

