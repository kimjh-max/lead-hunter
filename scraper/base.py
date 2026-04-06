"""크롤러 베이스 클래스."""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime

import httpx
from bs4 import BeautifulSoup

from config.settings import settings

logger = logging.getLogger(__name__)


@dataclass
class ScrapedEvent:
    """수집된 행사 정보."""
    title: str
    organizer: str = ""
    org_type: str = "other"
    event_type: str = ""
    description: str = ""
    start_date: datetime | None = None
    end_date: datetime | None = None
    location: str = ""
    url: str = ""
    contact_name: str = ""
    contact_department: str = ""
    contact_email: str = ""
    contact_phone: str = ""
    budget_info: str = ""
    source: str = ""


@dataclass
class ScrapedOrg:
    """수집된 기관 정보."""
    name: str
    org_type: str = "other"
    website: str = ""
    address: str = ""
    description: str = ""
    contacts: list[dict[str, str]] = field(default_factory=list)
    events: list[ScrapedEvent] = field(default_factory=list)
    source: str = ""


class BaseScraper(ABC):
    """크롤러 베이스 클래스. 모든 소스별 크롤러는 이 클래스를 상속."""

    source_name: str = "unknown"

    def __init__(self) -> None:
        self.client = httpx.AsyncClient(
            timeout=30.0,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                )
            },
            follow_redirects=True,
        )
        self.delay = settings.request_delay_seconds

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.client.aclose()

    async def fetch(self, url: str) -> str | None:
        """URL에서 HTML을 가져옴."""
        try:
            await asyncio.sleep(self.delay)
            response = await self.client.get(url)
            response.raise_for_status()
            return response.text
        except httpx.HTTPError as e:
            logger.error(f"[{self.source_name}] 요청 실패: {url} - {e}")
            return None

    def parse_html(self, html: str) -> BeautifulSoup:
        """HTML 파싱."""
        return BeautifulSoup(html, "lxml")

    @abstractmethod
    async def scrape_events(self) -> list[ScrapedEvent]:
        """행사 정보 수집. 각 소스별로 구현."""
        ...

    @abstractmethod
    async def scrape_organizations(self) -> list[ScrapedOrg]:
        """기관 정보 수집. 각 소스별로 구현."""
        ...

    async def run(self) -> tuple[list[ScrapedOrg], list[ScrapedEvent]]:
        """크롤링 실행."""
        logger.info(f"[{self.source_name}] 크롤링 시작...")
        orgs = await self.scrape_organizations()
        events = await self.scrape_events()
        logger.info(
            f"[{self.source_name}] 완료 - 기관: {len(orgs)}개, 행사: {len(events)}개"
        )
        return orgs, events
