from datetime import datetime, timezone
from html import escape as html_escape
from typing import Any, Dict, List, Optional, Union

import httpx

from app.core.config import settings
from app.core.logging import logger
from app.providers.base import BaseProviderAdapter, ProviderStatus


class ResendAdapter(BaseProviderAdapter):
    """
    Resend transactional & outreach email adapter.
    Handles password recovery, access request alerts, system notifications,
    and personalized cold outreach delivery.
    """

    def __init__(self):
        super().__init__("resend")
        self.base_url = "https://api.resend.com"

    @property
    def api_key(self) -> str:
        return settings.RESEND_API_KEY.strip() if settings.RESEND_API_KEY else ""

    @property
    def from_email(self) -> str:
        return settings.RESEND_FROM_EMAIL.strip() if settings.RESEND_FROM_EMAIL else "onboarding@resend.dev"

    @property
    def enabled(self) -> bool:
        return settings.RESEND_ENABLED

    def is_configured(self) -> bool:
        """Returns True if Resend is enabled and has a non-empty API key."""
        return bool(self.enabled and self.api_key)

    async def check_health(self) -> ProviderStatus:
        """Checks API connectivity and authentication against Resend /api_keys endpoint."""
        if not self.is_configured():
            return ProviderStatus(
                name=self.name,
                is_configured=False,
                is_healthy=False,
                status_message="Resend transactional email provider is unconfigured or disabled.",
                last_checked=datetime.now(timezone.utc),
            )
        try:
            headers = {"Authorization": f"Bearer {self.api_key}"}
            async with httpx.AsyncClient(timeout=5.0) as client:
                res = await client.get(f"{self.base_url}/api_keys", headers=headers)
                if res.status_code == 200:
                    return ProviderStatus(
                        name=self.name,
                        is_configured=True,
                        is_healthy=True,
                        status_message="Connected to Resend API (Full Access)",
                        last_checked=datetime.now(timezone.utc),
                    )
                # Sending-only API keys return 401 restricted_api_key on /api_keys, proving authentication succeeds
                if res.status_code == 401 and "restricted_api_key" in res.text:
                    return ProviderStatus(
                        name=self.name,
                        is_configured=True,
                        is_healthy=True,
                        status_message="Connected to Resend API (Verified Sending Key)",
                        last_checked=datetime.now(timezone.utc),
                    )
                return ProviderStatus(
                    name=self.name,
                    is_configured=True,
                    is_healthy=False,
                    status_message=f"Resend error HTTP {res.status_code}",
                    last_checked=datetime.now(timezone.utc),
                )

        except Exception as e:
            return ProviderStatus(
                name=self.name,
                is_configured=True,
                is_healthy=False,
                status_message=f"Healthcheck error: {str(e)}",
                last_checked=datetime.now(timezone.utc),
            )

    async def send_email(
        self,
        to: Union[str, List[str]],
        subject: str,
        html: str,
        text: Optional[str] = None,
        from_email: Optional[str] = None,
        reply_to: Optional[str] = None,
        cc: Optional[List[str]] = None,
        bcc: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Core low-level method to dispatch emails via Resend API.
        Returns a dict: {"success": bool, "id": Optional[str], "error": Optional[str]}
        """
        if not self.is_configured():
            return {
                "success": False,
                "id": None,
                "error": "Resend provider is not configured or disabled in settings.",
            }

        recipients = [to] if isinstance(to, str) else list(to)
        effective_from = from_email or self.from_email

        payload: Dict[str, Any] = {
            "from": effective_from,
            "to": recipients,
            "subject": subject,
            "html": html,
        }
        if text:
            payload["text"] = text
        if reply_to:
            payload["reply_to"] = reply_to
        if cc:
            payload["cc"] = cc
        if bcc:
            payload["bcc"] = bcc

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    f"{self.base_url}/emails",
                    headers=headers,
                    json=payload,
                )

                if response.status_code in (200, 201):
                    data = response.json()
                    email_id = data.get("id")
                    logger.info(f"Email successfully sent via Resend: ID={email_id} to={recipients}")
                    return {"success": True, "id": email_id, "error": None}

                error_data = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
                err_msg = error_data.get("message") or f"HTTP {response.status_code}: {response.text}"
                logger.warning(f"Resend email dispatch rejected: {err_msg}")
                return {"success": False, "id": None, "error": err_msg}

        except Exception as exc:
            logger.error(f"Resend network/connection failure: {exc}")
            return {"success": False, "id": None, "error": str(exc)}

    async def send_password_reset_email(self, to_email: str, reset_token: str) -> bool:
        """Sends password reset email with secure token link."""
        frontend_url = settings.BACKEND_CORS_ORIGINS[0] if settings.BACKEND_CORS_ORIGINS else "http://localhost:3000"
        reset_link = f"{frontend_url}/reset-password?token={reset_token}"

        html = f"""
        <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; max-width: 560px; margin: 0 auto; padding: 32px 24px; color: #1e293b; background-color: #ffffff; border: 1px solid #e2e8f0; border-radius: 8px;">
            <div style="margin-bottom: 24px;">
                <span style="font-size: 20px; font-weight: 700; color: #0f172a; letter-spacing: -0.5px;">LeadFlow</span>
            </div>
            <h2 style="font-size: 18px; font-weight: 600; color: #0f172a; margin-top: 0; margin-bottom: 12px;">Reset your password</h2>
            <p style="font-size: 14px; line-height: 1.6; color: #475569; margin-bottom: 24px;">
                We received a request to reset your LeadFlow account password. Click the button below to set a new password. This link will expire in 1 hour.
            </p>
            <div style="margin-bottom: 28px;">
                <a href="{reset_link}" style="background-color: #0284c7; color: #ffffff; padding: 12px 24px; font-size: 14px; font-weight: 500; text-decoration: none; border-radius: 6px; display: inline-block;">Reset Password</a>
            </div>
            <p style="font-size: 13px; line-height: 1.5; color: #94a3b8; margin-top: 0; margin-bottom: 0;">
                If you did not request a password reset, you can safely disregard this email. Your password will remain unchanged.
            </p>
        </div>
        """
        res = await self.send_email(
            to=to_email,
            subject="Reset your LeadFlow account password",
            html=html,
            text=f"Reset your LeadFlow password by following this link: {reset_link} (Expires in 1 hour).",
        )
        return res.get("success", False)

    async def send_welcome_email(self, to_email: str, full_name: Optional[str], org_name: str) -> bool:
        """Sends a welcome email upon workspace initialization."""
        frontend_url = settings.BACKEND_CORS_ORIGINS[0] if settings.BACKEND_CORS_ORIGINS else "http://localhost:3000"
        login_link = f"{frontend_url}/login"
        name = full_name or to_email.split("@")[0].title()
        safe_name = html_escape(name)
        safe_org_name = html_escape(org_name)

        html = f"""
        <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; max-width: 560px; margin: 0 auto; padding: 32px 24px; color: #1e293b; background-color: #ffffff; border: 1px solid #e2e8f0; border-radius: 8px;">
            <div style="margin-bottom: 24px;">
                <span style="font-size: 20px; font-weight: 700; color: #0f172a; letter-spacing: -0.5px;">LeadFlow</span>
            </div>
            <h2 style="font-size: 18px; font-weight: 600; color: #0f172a; margin-top: 0; margin-bottom: 12px;">Welcome to LeadFlow, {safe_name}!</h2>
            <p style="font-size: 14px; line-height: 1.6; color: #475569; margin-bottom: 20px;">
                Your workspace for <strong>{safe_org_name}</strong> is ready. You can now build high-intent B2B audience searches, qualify leads across 22 intent signals, and generate AI-personalized outreach copy.
            </p>
            <div style="margin-bottom: 28px;">
                <a href="{login_link}" style="background-color: #0284c7; color: #ffffff; padding: 12px 24px; font-size: 14px; font-weight: 500; text-decoration: none; border-radius: 6px; display: inline-block;">Go to Workspace</a>
            </div>
            <p style="font-size: 13px; line-height: 1.5; color: #94a3b8; margin-top: 0; margin-bottom: 0;">
                If you have questions, our engineering team is here to help.
            </p>
        </div>
        """
        res = await self.send_email(
            to=to_email,
            subject=f"Welcome to LeadFlow - {org_name}",
            html=html,
            text=f"Welcome to LeadFlow, {name}! Your workspace for {org_name} is active: {login_link}",
        )
        return res.get("success", False)

    async def send_access_request_notification(
        self,
        admin_email: str,
        applicant_name: str,
        applicant_email: str,
        org_name: str,
        requested_role: str,
    ) -> bool:
        """Notifies administrator of a newly submitted team access request."""
        frontend_url = settings.BACKEND_CORS_ORIGINS[0] if settings.BACKEND_CORS_ORIGINS else "http://localhost:3000"
        admin_link = f"{frontend_url}/admin"
        safe_org_name = html_escape(org_name)
        safe_applicant_name = html_escape(applicant_name)
        safe_applicant_email = html_escape(applicant_email)
        safe_role = html_escape(requested_role)

        html = f"""
        <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; max-width: 560px; margin: 0 auto; padding: 32px 24px; color: #1e293b; background-color: #ffffff; border: 1px solid #e2e8f0; border-radius: 8px;">
            <div style="margin-bottom: 24px;">
                <span style="font-size: 20px; font-weight: 700; color: #0f172a; letter-spacing: -0.5px;">LeadFlow</span>
            </div>
            <h2 style="font-size: 18px; font-weight: 600; color: #0f172a; margin-top: 0; margin-bottom: 12px;">New access request pending review</h2>
            <p style="font-size: 14px; line-height: 1.6; color: #475569; margin-bottom: 16px;">
                A new user has requested access to <strong>{safe_org_name}</strong>:
            </p>
            <ul style="font-size: 14px; line-height: 1.6; color: #334155; margin-bottom: 24px;">
                <li><strong>Name:</strong> {safe_applicant_name}</li>
                <li><strong>Email:</strong> {safe_applicant_email}</li>
                <li><strong>Requested Role:</strong> {safe_role}</li>
            </ul>
            <div style="margin-bottom: 24px;">
                <a href="{admin_link}" style="background-color: #0f172a; color: #ffffff; padding: 10px 20px; font-size: 14px; font-weight: 500; text-decoration: none; border-radius: 6px; display: inline-block;">Review Access Request</a>
            </div>
        </div>
        """
        res = await self.send_email(
            to=admin_email,
            subject=f"Access Request: {applicant_name} ({org_name})",
            html=html,
            text=f"{applicant_name} ({applicant_email}) requested {requested_role} access to {org_name}. Review at: {admin_link}",
        )
        return res.get("success", False)

    async def send_access_request_decision(
        self,
        applicant_email: str,
        applicant_name: str,
        org_name: str,
        approved: bool,
        role: str,
        rejection_reason: Optional[str] = None,
    ) -> bool:
        """Sends notification to applicant when their access request is approved or rejected."""
        frontend_url = settings.BACKEND_CORS_ORIGINS[0] if settings.BACKEND_CORS_ORIGINS else "http://localhost:3000"
        login_link = f"{frontend_url}/login"
        safe_applicant_name = html_escape(applicant_name)
        safe_org_name = html_escape(org_name)
        safe_role = html_escape(role)

        if approved:
            subject = f"Your access request to {org_name} was approved!"
            html = f"""
            <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; max-width: 560px; margin: 0 auto; padding: 32px 24px; color: #1e293b; background-color: #ffffff; border: 1px solid #e2e8f0; border-radius: 8px;">
                <div style="margin-bottom: 24px;">
                    <span style="font-size: 20px; font-weight: 700; color: #0f172a; letter-spacing: -0.5px;">LeadFlow</span>
                </div>
                <h2 style="font-size: 18px; font-weight: 600; color: #166534; margin-top: 0; margin-bottom: 12px;">Access Request Approved</h2>
                <p style="font-size: 14px; line-height: 1.6; color: #475569; margin-bottom: 20px;">
                    Hi {safe_applicant_name}, your request to join <strong>{safe_org_name}</strong> as <strong>{safe_role}</strong> has been approved. You can now sign in with your credentials.
                </p>
                <div style="margin-bottom: 28px;">
                    <a href="{login_link}" style="background-color: #16a34a; color: #ffffff; padding: 12px 24px; font-size: 14px; font-weight: 500; text-decoration: none; border-radius: 6px; display: inline-block;">Sign In to LeadFlow</a>
                </div>
            </div>
            """
            text = f"Your access request to {org_name} as {role} was approved. Sign in at {login_link}"
        else:
            safe_reason = html_escape(rejection_reason) if rejection_reason else None
            reason_text = f"<p style='font-size: 14px; color: #64748b; margin-top: 8px;'><strong>Reason:</strong> {safe_reason}</p>" if safe_reason else ""
            subject = f"Update regarding your access request to {org_name}"
            html = f"""
            <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; max-width: 560px; margin: 0 auto; padding: 32px 24px; color: #1e293b; background-color: #ffffff; border: 1px solid #e2e8f0; border-radius: 8px;">
                <div style="margin-bottom: 24px;">
                    <span style="font-size: 20px; font-weight: 700; color: #0f172a; letter-spacing: -0.5px;">LeadFlow</span>
                </div>
                <h2 style="font-size: 18px; font-weight: 600; color: #991b1b; margin-top: 0; margin-bottom: 12px;">Access Request Not Approved</h2>
                <p style="font-size: 14px; line-height: 1.6; color: #475569; margin-bottom: 12px;">
                    Hi {safe_applicant_name}, your request to join <strong>{safe_org_name}</strong> was not approved at this time.
                </p>
                {reason_text}
            </div>
            """
            text = f"Your access request to {org_name} was not approved. Reason: {rejection_reason or 'No reason provided.'}"

        res = await self.send_email(to=applicant_email, subject=subject, html=html, text=text)
        return res.get("success", False)

    async def send_outreach_email(
        self,
        to_email: str,
        subject: str,
        body: str,
        reply_to: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Sends an approved AI cold outreach email directly to a prospect contact.
        Formats plain-text copy into clean, deliverable business email HTML.
        """
        # Convert linebreaks to HTML paragraphs for clean formatting. Escape first, then turn
        # single newlines into <br/>, so the approved draft text can never break out of its <p>.
        paragraphs = [p.strip() for p in body.split("\n\n") if p.strip()]
        html_paragraphs = "".join(
            f"<p style='margin: 0 0 16px 0; font-size: 15px; line-height: 1.6; color: #1e293b;'>{html_escape(p).replace(chr(10), '<br/>')}</p>"
            for p in paragraphs
        )

        html = f"""
        <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; max-width: 600px; margin: 0; padding: 16px 0; color: #1e293b;">
            {html_paragraphs}
        </div>
        """
        return await self.send_email(
            to=to_email,
            subject=subject,
            html=html,
            text=body,
            reply_to=reply_to,
        )
