"""크롤링 엔진 오케스트레이터 - 모든 소스를 통합 실행."""

import asyncio
import logging
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from database.models import Organization, Contact, Event, OrgType
from scraper.base import BaseScraper, ScrapedEvent, ScrapedOrg
from scraper.sources.kstartup import KStartupScraper
from scraper.sources.festa import FestaScraper
from scraper.sources.eventbrite import EventbriteScraper
from scraper.sources.gov_events import GovEventsScraper
from config.settings import settings

logger = logging.getLogger(__name__)


# 등록된 크롤러 목록 (새 소스 추가 시 여기에 등록)
REGISTERED_SCRAPERS: list[type[BaseScraper]] = [
    KStartupScraper,
    FestaScraper,
    EventbriteScraper,
    GovEventsScraper,
]


class CrawlEngine:
    """크롤링 엔진 - 모든 소스에서 리드를 수집하고 DB에 저장."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def run_all(self) -> dict[str, int]:
        """모든 등록된 크롤러 실행."""
        stats = {"organizations": 0, "events": 0, "contacts": 0}

        for scraper_cls in REGISTERED_SCRAPERS:
            try:
                async with scraper_cls() as scraper:
                    orgs, events = await scraper.run()

                    for org_data in orgs:
                        await self._save_organization(org_data)
                        stats["organizations"] += 1

                    for event_data in events:
                        await self._save_event(event_data)
                        stats["events"] += 1

                    await self.db.commit()

            except Exception as e:
                logger.error(f"크롤러 {scraper_cls.source_name} 실행 실패: {e}")
                await self.db.rollback()
                continue

        logger.info(
            f"크롤링 완료 - 기관: {stats['organizations']}개, "
            f"행사: {stats['events']}개"
        )
        return stats

    async def run_single(self, source_name: str) -> dict[str, int]:
        """특정 소스만 크롤링 실행."""
        stats = {"organizations": 0, "events": 0, "contacts": 0}

        scraper_cls = next(
            (s for s in REGISTERED_SCRAPERS if s.source_name == source_name),
            None,
        )
        if not scraper_cls:
            logger.error(f"알 수 없는 소스: {source_name}")
            return stats

        async with scraper_cls() as scraper:
            orgs, events = await scraper.run()

            for org_data in orgs:
                await self._save_organization(org_data)
                stats["organizations"] += 1

            for event_data in events:
                await self._save_event(event_data)
                stats["events"] += 1

            await self.db.commit()

        return stats

    async def _save_organization(self, data: ScrapedOrg) -> Organization:
        """기관 정보를 DB에 저장 (중복 체크)."""
        result = await self.db.execute(
            select(Organization).where(Organization.name == data.name)
        )
        org = result.scalar_one_or_none()

        if org:
            # 기존 기관 업데이트
            if data.website and not org.website:
                org.website = data.website
            if data.description and not org.description:
                org.description = data.description
            org.updated_at = datetime.utcnow()
        else:
            # 새 기관 생성
            org_type = self._map_org_type(data.org_type)
            org = Organization(
                name=data.name,
                org_type=org_type,
                website=data.website,
                address=data.address,
                description=data.description,
            )
            self.db.add(org)
            await self.db.flush()

        # 담당자 정보 저장
        for contact_data in data.contacts:
            await self._save_contact(org.id, contact_data, data.source)

        return org

    async def _save_event(self, data: ScrapedEvent) -> None:
        """행사 정보를 DB에 저장."""
        # 기관 찾기 또는 생성
        if data.organizer:
            result = await self.db.execute(
                select(Organization).where(Organization.name == data.organizer)
            )
            org = result.scalar_one_or_none()

            if not org:
                org = Organization(
                    name=data.organizer,
                    org_type=self._map_org_type(data.org_type),
                )
                self.db.add(org)
                await self.db.flush()

            event = Event(
                organization_id=org.id,
                title=data.title,
                event_type=data.event_type,
                description=data.description,
                start_date=data.start_date,
                end_date=data.end_date,
                location=data.location,
                url=data.url,
                budget_info=data.budget_info,
                source=data.source,
            )
            self.db.add(event)

            # 담당자 정보가 있으면 저장
            if data.contact_email or data.contact_name:
                await self._save_contact(org.id, {
                    "name": data.contact_name,
                    "department": data.contact_department,
                    "email": data.contact_email,
                    "phone": data.contact_phone,
                }, data.source)

    async def _save_contact(
        self, org_id: int, data: dict[str, str], source: str
    ) -> None:
        """담당자 정보 저장 (중복 체크)."""
        email = data.get("email", "")
        if not email:
            return

        result = await self.db.execute(
            select(Contact).where(Contact.email == email)
        )
        existing = result.scalar_one_or_none()

        if not existing:
            contact = Contact(
                organization_id=org_id,
                name=data.get("name", ""),
                department=data.get("department", ""),
                position=data.get("position", ""),
                email=email,
                phone=data.get("phone", ""),
                source=source,
            )
            self.db.add(contact)

    @staticmethod
    def _map_org_type(type_str: str) -> OrgType:
        """문자열을 OrgType enum으로 변환."""
        mapping = {
            "government": OrgType.GOVERNMENT,
            "local_government": OrgType.LOCAL_GOV,
            "public_agency": OrgType.PUBLIC_AGENCY,
            "accelerator": OrgType.ACCELERATOR,
            "vc": OrgType.VC,
            "private": OrgType.PRIVATE,
            "association": OrgType.ASSOCIATION,
            "university": OrgType.UNIVERSITY,
        }
        return mapping.get(type_str, OrgType.OTHER)
