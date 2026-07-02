"""
邮件发送模块 - SMTP 方式（解决 Cloudflare 拦截问题）
使用 Resend SMTP Relay 发送邮件
"""
import smtplib
import os
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

logger = logging.getLogger(__name__)

# Resend SMTP 配置
SMTP_HOST = "smtp.resend.com"
SMTP_PORT = 587
SMTP_USER = "resend"  # Resend SMTP 用户名固定为 "resend"
FROM_EMAIL = "onboarding@resend.dev"  # 临时发件人（Resend 免费域名）
FROM_NAME = "节能阀"

# 是否已初始化
_initialized = False


def init():
    """初始化邮件服务，检查 API Key 是否配置"""
    global _initialized
    api_key = os.environ.get("RESEND_API_KEY", "")
    if not api_key:
        logger.warning("RESEND_API_KEY 未配置，邮件发送功能不可用")
        return
    _initialized = True
    logger.info("邮件服务初始化完成 (SMTP: %s)", SMTP_HOST)


def send_email(to_email: str, subject: str, html_body: str) -> bool:
    """
    发送邮件
    :param to_email: 收件人邮箱
    :param subject: 邮件主题
    :param html_body: HTML 格式邮件内容
    :return: 是否发送成功
    """
    api_key = os.environ.get("RESEND_API_KEY", "")
    if not api_key:
        logger.error("RESEND_API_KEY 未配置")
        return False

    try:
        msg = MIMEMultipart("alternative")
        msg["From"] = f"{FROM_NAME} <{FROM_EMAIL}>"
        msg["To"] = to_email
        msg["Subject"] = subject
        msg.attach(MIMEText(html_body, "html", "utf-8"))

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as server:
            server.starttls()
            server.login(SMTP_USER, api_key)
            server.sendmail(FROM_EMAIL, [to_email], msg.as_string())

        logger.info("邮件发送成功: %s -> %s", subject, to_email)
        return True

    except Exception as e:
        logger.error("邮件发送失败: %s", e)
        return False


def send_api_key_email(to_email: str, api_key: str, portal_url: str) -> bool:
    """
    发送 API Key 邮件
    :param to_email: 收件人邮箱
    :param api_key: 用户的 API Key
    :param portal_url: 面板地址
    :return: 是否发送成功
    """
    subject = "您的节能阀 API Key"
    html_body = f"""
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
        <div style="background: #FFF8F0; border-radius: 12px; padding: 30px; border: 1px solid #FFE4CC;">
            <h2 style="color: #FF6B35; margin-top: 0;">🔑 您的 API Key</h2>
            <p style="color: #333; line-height: 1.6;">您好！以下是您的节能阀 API Key，请妥善保管：</p>
            <div style="background: #1a1a2e; border-radius: 8px; padding: 16px; margin: 20px 0;">
                <code style="color: #00ff88; font-size: 14px; word-break: break-all;">{api_key}</code>
            </div>
            <div style="background: #fff; border-radius: 8px; padding: 16px; margin: 20px 0; border: 1px solid #eee;">
                <h3 style="margin-top: 0; color: #333;">📖 快速开始</h3>
                <p style="color: #666; font-size: 14px;">将您的 API 调用地址改为：</p>
                <code style="color: #FF6B35; font-size: 13px;">http://154.8.211.17/gateway/v1</code>
                <p style="color: #666; font-size: 14px; margin-top: 10px;">请求头添加：</p>
                <code style="color: #666; font-size: 13px;">Authorization: Bearer {api_key}</code>
            </div>
            <p style="color: #666; font-size: 14px;">
                💰 每月免费 1000 次调用，超出后仅 ¥0.01/次<br>
                📊 账户面板：<a href="{portal_url}" style="color: #FF6B35;">{portal_url}</a>
            </p>
            <hr style="border: none; border-top: 1px solid #eee; margin: 20px 0;">
            <p style="color: #999; font-size: 12px;">节能阀 - 让每一分钱都花在刀刃上</p>
        </div>
    </div>
    """
    return send_email(to_email, subject, html_body)
