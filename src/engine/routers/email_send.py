import smtplib
import logging
import asyncio
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from config import (
    SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_FROM_NAME,
    SHARE_BASE_URL,
)

router = APIRouter()
log = logging.getLogger(__name__)


class SendEmailRequest(BaseModel):
    to: str = Field(..., min_length=1, description="收件人邮箱")
    subject: str = Field(..., min_length=1, max_length=120)
    body: str = Field(..., min_length=1, max_length=10000)
    share_url: Optional[str] = Field(None, description="分享链接，会附加在邮件末尾")


class SendEmailResponse(BaseModel):
    ok: bool
    message: str


def _check_config():
    if not SMTP_USER or not SMTP_PASSWORD:
        raise HTTPException(
            status_code=500,
            detail="邮件服务未配置。请在 .env 中设置 SMTP_USER 和 SMTP_PASSWORD",
        )


def _build_html(body: str, share_url: Optional[str] = None) -> str:
    """Build a warm, readable HTML email."""
    paragraphs = body.strip().split("\n")
    body_html = ""
    for p in paragraphs:
        if p.strip():
            body_html += f'<p style="margin:0 0 12px;line-height:1.8">{p.strip()}</p>\n'

    share_block = ""
    if share_url:
        share_block = f"""
        <div style="margin:28px 0 0;padding:20px 0 0;border-top:1px solid #E8E4DC">
            <p style="margin:0 0 10px;color:#8B8878;font-size:13px">
                点击下方按钮查看完整内容（含插图）：
            </p>
            <a href="{share_url}" style="
                display:inline-block;
                padding:12px 28px;
                background:#B8D4C2;
                color:#2D4738;
                text-decoration:none;
                border-radius:20px;
                font-size:15px;
                font-weight:600
            ">查看日记 ✨</a>
        </div>"""

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="UTF-8"></head>
<body style="
    margin:0;padding:24px;
    background:#F8F6F3;
    font-family:-apple-system,BlinkMacSystemFont,'PingFang SC','Microsoft YaHei',sans-serif;
    color:#3D3929
">
    <div style="max-width:560px;margin:0 auto;background:#fff;border-radius:16px;padding:32px 24px;box-shadow:0 2px 12px rgba(0,0,0,0.06)">
        <div style="text-align:center;margin-bottom:24px">
            <div style="font-size:28px;margin-bottom:4px">📨</div>
            <div style="font-size:13px;color:#B0ADA0">来自 {SMTP_FROM_NAME}</div>
        </div>
        {body_html}
        {share_block}
        <div style="margin-top:28px;text-align:center;font-size:12px;color:#B0ADA0">
            —— 数字实习生 · 知己 ✨ ——
        </div>
    </div>
</body>
</html>"""


def _send_sync(to: str, subject: str, html: str):
    """Blocking SMTP send. Runs in a thread via asyncio."""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"{SMTP_FROM_NAME} <{SMTP_USER}>"
    msg["To"] = to
    msg.attach(MIMEText(html, "html", "utf-8"))

    if SMTP_PORT == 465:
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=15) as server:
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(SMTP_USER, [to], msg.as_string())
    else:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(SMTP_USER, [to], msg.as_string())


@router.post("/send", response_model=SendEmailResponse)
async def send_email(req: SendEmailRequest):
    _check_config()

    html = _build_html(req.body, req.share_url)

    try:
        await asyncio.to_thread(_send_sync, req.to, req.subject, html)
    except smtplib.SMTPAuthenticationError:
        raise HTTPException(status_code=502, detail="邮件认证失败，请检查 SMTP 用户名和授权码")
    except smtplib.SMTPConnectError:
        raise HTTPException(status_code=502, detail=f"无法连接邮件服务器 {SMTP_HOST}:{SMTP_PORT}")
    except Exception as e:
        log.warning("email send failed: %s", e)
        raise HTTPException(status_code=502, detail=f"邮件发送失败：{e}")

    log.info("email sent to %s: %s", req.to, req.subject)
    return SendEmailResponse(ok=True, message="邮件已发送")


@router.get("/config")
async def get_email_config():
    """Return whether email is configured."""
    return {
        "configured": bool(SMTP_USER and SMTP_PASSWORD),
        "from_name": SMTP_FROM_NAME,
        "from_addr": SMTP_USER if SMTP_USER else None,
    }