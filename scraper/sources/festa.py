"""Festa.io 크롤러 - 국내 IT/스타트업 행사 수집."""

from __future__ import annotations

import logging
from datetime import datetime

from scraper.base import BaseScraper, ScrapedEvent, ScrapedOrg

logger = logging.getLogger(__name__)

BASE_URL = "https://festa.io"
API_URL = f"{BASE_URL}/api/v1/events"


class FestaScraper(BaseScraper):
    """Festa.io 행사 크롤러."""

    source_name = "festa"

    async def scrape_events(self) -> list[ScrapedEvent]:
        """Festa API로 행사 목록 수집."""
        events: list[ScrapedEvent] = []

        # Festa는 API를 제공함
        params = {
            "page": 1,
            "pageSize": 50,
            "order": "startDate",
            "excludeExternalEvents": "false",
        }

        try:
            response = await self.client.get(API_URL, params=params)
            if response.status_code != 200:
                # API 사용 불가시 HTML 폴백
                return await self._scrape_html()

            data = response.json()
            rows = data if isinstance(data, list) else data.get("rows", [])

            for item in rows:
                title = item.get("name", item.get("title", ""))
                if not title:
                    continue

                host = item.get("hostName", item.get("organizer", ""))
                event_id = item.get("eventId", "")
                url = f"{BASE_URL}/{event_id}" if event_id else ""

                start = item.get("startDate", "")
                end = item.get("endDate", "")
                start_dt = self._parse_date(start) if start else None
                end_dt = self._parse_date(end) if end else None

                events.append(ScrapedEvent(
                    title=title,
                    organizer=host,
                    org_type="private",
                    event_type=item.get("category", "행사"),
                    description=item.get("description", "")[:500],
                    start_date=start_dt,
                    end_date=end_dt,
                    location=item.get("location", ""),
                    url=url,
                    source=self.source_name,
                ))

        except Exception as e:
            logger.error(f"[festa] API 호출 실패: {e}")
            return await self._scrape_html()

        logger.info(f"[festa] {len(events)}개 행사 수집 완료")
        return events

    async def _scrape_html(self) -> list[ScrapedEvent]:
        """HTML 폴백 크롤링."""
        events: list[ScrapedEvent] = []
        html = await self.fetch(f"{BASE_URL}/events")
        if not html:
            return events

        soup = self.parse_html(html)
        cards = soup.select("[class*='EventCard'], [class*='event-card'], .event-item")

        for card in cards:
            title_el = card.select_one("h3, h2, .title, [class*='title']")
            if not title_el:
                continue

            title = title_el.get_text(strip=True)
            link_el = card.select_one("a[href]")
            link = link_el["href"] if link_el else ""
            if link and not link.startswith("http"):
                link = BASE_URL + link

            host_el = card.select_one("[class*='host'], [class*='organizer'], .org")
            host = host_el.get_text(strip=True) if host_el else ""

            events.append(ScrapedEvent(
                title=title,
                organizer=host,
                org_type="private",
                event_type="IT/스타트업",
                url=link,
                source=self.source_name,
            ))

        return events

    async def scrape_organizations(self) -> list[ScrapedOrg]:
        """행사 주최자 기관 정보 수집."""
        events = await self.scrape_events()
        orgs: list[ScrapedOrg] = []
        seen: set[str] = set()

        for event in events:
            if event.organizer and event.organizer not in seen:
                seen.add(event.organizer)
                orgs.append(ScrapedOrg(
                    name=event.organizer,
                    org_type="private",
                    source=self.source_name,
                    events=[event],
                ))

        return orgs

    @staticmethod
    def _parse_date(date_str: str) -> datetime | None:
        """날짜 문자열 파싱."""
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
            try:
                return datetime.strptime(date_str[:19], fmt)
            except ValueError:
                continue
        return None
