"""Send account verification and password recovery codes over configured SMTP."""
from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage


def send_otp_email(recipient: str, code: str, purpose: str) -> None:
    host = os.environ.get("SMTP_HOST", "").strip()
    sender = os.environ.get("SMTP_FROM_EMAIL", "").strip()
    if not host or not sender:
        raise RuntimeError(
            "Email delivery is not configured. Set SMTP_HOST and SMTP_FROM_EMAIL in .env."
        )

    try:
        port = int(os.environ.get("SMTP_PORT", "587"))
    except ValueError as error:
        raise RuntimeError("SMTP_PORT must be a valid port number in .env.") from error
    username = os.environ.get("SMTP_USERNAME", "").strip()
    password = os.environ.get("SMTP_PASSWORD", "")
    use_ssl = os.environ.get("SMTP_USE_SSL", "").strip().lower() in {"1", "true", "yes"}
    action = "verify your email" if purpose == "verify" else "reset your password"

    message = EmailMessage()
    message["Subject"] = "CI Failure Explainer verification code"
    message["From"] = sender
    message["To"] = recipient
    message.set_content(
        f"Your code to {action} is: {code}\n\n"
        "This code expires in 10 minutes and can only be used once. "
        "If you did not request it, you can ignore this message."
    )

    try:
        if use_ssl:
            with smtplib.SMTP_SSL(host, port, timeout=15) as server:
                if username:
                    server.login(username, password)
                server.send_message(message)
        else:
            with smtplib.SMTP(host, port, timeout=15) as server:
                server.ehlo()
                server.starttls()
                server.ehlo()
                if username:
                    server.login(username, password)
                server.send_message(message)
    except (OSError, smtplib.SMTPException) as error:
        raise RuntimeError(
            "Email could not be sent. Check the SMTP settings in .env."
        ) from error
