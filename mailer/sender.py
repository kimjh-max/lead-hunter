"""콜드메일 발송 엔진."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import aiosmtplib
from jinja2 import Environment, FileSystemLoader
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import settings
from database.models import Contact, EmailLog, LeadStatus, Organization

logger = logging.getLogger(__name__)


class ColdMailer:
    """콜드메일 발송 엔진."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.template_env = Environment(
            loader=FileSystemLoader(str(settings.templates_dir)),
            autoescape=True,
        )

    async def send_campaign(
        self,
        product_slug: str,
        template_name: str = "default",
        max_count: int | None = None,
    ) -> dict[str, int]:
        """캠페인 발송 - 미발송 리드에게 콜드메일 발송."""
        stats = {"sent": 0, "failed": 0, "skipped": 0}

        # 오늘 발송 건수 확인 (일일 한도)
        today_count = await self._get_today_send_count()
        remaining = settings.max_emails_per_day - today_count
        if remaining <= 0:
            logger.warning("일일 발송 한도 도달")
            return stats

        # 발송 대상 조회: 신규 또는 검증된 리드 중 미발송
        query = (
            select(Contact)
            .where(Contact.status.in_([LeadStatus.NEW, LeadStatus.VERIFIED]))
            .where(Contact.email.isnot(None))
            .where(Contact.email != "")
            .limit(min(remaining, max_count or remaining))
        )
        result = await self.db.execute(query)
        contacts = result.scalars().all()

        for contact in contacts:
            try:
                # 시간당 한도 체크
                hour_count = await self._get_hour_send_count()
                if hour_count >= settings.max_emails_per_hour:
                    logger.info("시간당 한도 도달, 대기 중...")
                    await asyncio.sleep(60)
                    continue

                # 기관 정보 조회
                org_result = await self.db.execute(
                    select(Organization).where(
                        Organization.id == contact.organization_id
                    )
                )
                org = org_result.scalar_one_or_none()

                # 메일 발송
                success = await self._send_email(
                    contact=contact,
                    organization=org,
                    product_slug=product_slug,
                    template_name=template_name,
                )

                if success:
                    contact.status = LeadStatus.CONTACTED
                    stats["sent"] += 1
                else:
                    stats["failed"] += 1

                await self.db.commit()

                # 발송 간격 대기
                await asyncio.sleep(settings.email_interval_seconds)

            except Exception as e:
                logger.error(f"발송 실패 ({contact.email}): {e}")
                stats["failed"] += 1
                continue

        logger.info(
            f"캠페인 완료 - 발송: {stats['sent']}, "
            f"실패: {stats['failed']}, 건너뜀: {stats['skipped']}"
        )
        return stats

    async def _send_email(
        self,
        contact: Contact,
        organization: Organization | None,
        product_slug: str,
        template_name: str,
    ) -> bool:
        """개별 이메일 발송."""
        try:
            # 템플릿 렌더링
            subject, html_body = self._render_template(
                template_name=template_name,
                product_slug=product_slug,
                contact_name=contact.name or "담당자",
                org_name=organization.name if organization else "",
                department=contact.department or "",
            )

            # MIME 메시지 생성
            msg = MIMEMultipart("alternative")
            msg["From"] = f"{settings.sender_name} <{settings.sender_email}>"
            msg["To"] = contact.email
            msg["Subject"] = subject

            # 트래킹 픽셀 삽입 (발송 로그 ID는 flush 후 확보)
            log = EmailLog(
                contact_id=contact.id,
                product_slug=product_slug,
                subject=subject,
                template_name=template_name,
                sent_at=datetime.utcnow(),
            )
            self.db.add(log)
            await self.db.flush()  # log.id 확보

            # 오픈 추적 픽셀을 HTML 끝에 삽입
            tracking_url = f"https://localhost:8500/api/track/open/{log.id}"
            tracking_pixel = f'<img src="{tracking_url}" width="1" height="1" style="display:none;" alt="" />'
            if "</body>" in html_body:
                html_body = html_body.replace("</body>", f"{tracking_pixel}</body>")
            else:
                html_body += tracking_pixel

            msg.attach(MIMEText(html_body, "html", "utf-8"))

            # SMTP 발송
            await aiosmtplib.send(
                msg,
                hostname=settings.smtp_host,
                port=settings.smtp_port,
                username=settings.smtp_user,
                password=settings.smtp_password,
                start_tls=True,
            )

            logger.info(f"메일 발송 성공: {contact.email} (log_id={log.id})")
            return True

        except Exception as e:
            logger.error(f"메일 발송 실패 ({contact.email}): {e}")

            # 반송 처리
            log = EmailLog(
                contact_id=contact.id,
                product_slug=product_slug,
                subject="[발송실패]",
                template_name=template_name,
                bounced=True,
                error_message=str(e),
            )
            self.db.add(log)

            return False

    def _render_template(
        self,
        template_name: str,
        product_slug: str,
        contact_name: str,
        org_name: str,
        department: str,
    ) -> tuple[str, str]:
        """메일 템플릿 렌더링. (제목, HTML 본문) 반환."""
        try:
            template = self.template_env.get_template(
                f"{product_slug}/{template_name}.html"
            )
        except Exception:
            template = self.template_env.get_template("default.html")

        product_info = settings.products.get(product_slug, {})

        html = template.render(
            contact_name=contact_name,
            org_name=org_name,
            department=department,
            product_name=product_info.get("name", ""),
            product_description=product_info.get("description", ""),
            demo_url=product_info.get("demo_url", ""),
            sender_name=settings.sender_name,
        )

        # 제목은 템플릿 첫 줄에서 추출 (<!-- subject: ... --> 형식)
        subject = f"[{settings.sender_name}] {product_info.get('name', '')} 소개"
        if "<!-- subject:" in html:
            start = html.index("<!-- subject:") + 13
            end = html.index("-->", start)
            subject = html[start:end].strip()

        return subject, html

    async def _get_today_send_count(self) -> int:
        """오늘 발송 건수 조회."""
        today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        result = await self.db.execute(
            select(func.count(EmailLog.id)).where(EmailLog.sent_at >= today)
        )
        return result.scalar() or 0

    async def _get_hour_send_count(self) -> int:
        """최근 1시간 발송 건수 조회."""
        from datetime import timedelta
        one_hour_ago = datetime.utcnow() - timedelta(hours=1)
        result = await self.db.execute(
            select(func.count(EmailLog.id)).where(EmailLog.sent_at >= one_hour_ago)
        )
        return result.scalar() or 0
