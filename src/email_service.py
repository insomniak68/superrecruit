import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart


def send_assessment_email(candidate_name: str, candidate_email: str, token: str,
                          base_url: str = "http://localhost:8000",
                          smtp_config: dict | None = None):
    link = f"{base_url}/assess/{token}"
    subject = f"Skills Assessment Invitation — SuperRecruit"
    body = f"""Hi {candidate_name},

You've been invited to complete a skills assessment as part of our hiring process.

Click the link below to begin your assessment:
{link}

Important notes:
• Complete all sections in one sitting
• Each section is timed individually
• You may use documentation but not AI assistants
• The link expires in 72 hours

Good luck!

— SuperRecruit Assessment Platform
"""

    if smtp_config and smtp_config.get("host"):
        msg = MIMEMultipart()
        msg["From"] = smtp_config.get("from", "assessments@superrecruit.dev")
        msg["To"] = candidate_email
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))
        with smtplib.SMTP(smtp_config["host"], smtp_config.get("port", 587)) as server:
            server.starttls()
            server.login(smtp_config["user"], smtp_config["password"])
            server.send_message(msg)
        print(f"[Email] Sent assessment to {candidate_email}")
    else:
        print(f"\n{'='*60}")
        print(f"[DRY RUN] Assessment Email to: {candidate_email}")
        print(f"Subject: {subject}")
        print(f"{'='*60}")
        print(body)
        print(f"{'='*60}\n")

    return link
