"""K-Startup (창업넷) 크롤러 - 정부/공공 스타트업 행사 수집."""

import logging
import re
from datetime import datetime

from scraper.base import BaseScraper, ScrapedEvent, ScrapedOrg

logger = logging.getLogger(__name__)

# K-Startup 행사/프로그램 목록 페이지
BASE_URL = "https://www.k-startup.go.kr"
EVENT_LIST_URL = f"{BASE_URL}/web/contents/list.do?schM=view&pbancSn=&pbancEndYn=N&bizPbancCtgr=all&menuApply=&menuNo=200568"


class KStartupScraper(BaseScraper):
    """K-Startup 행사 크롤러."""

    source_name = "k-startup"

    async def scrape_events(self) -> list[ScrapedEvent]:
        """K-Startup 행사/프로그램 목록 수집."""
        events: list[ScrapedEvent] = []

        html = await self.fetch(EVENT_LIST_URL)
        if not html:
            return events

        soup = self.parse_html(html)
        items = soup.select(".list_item, .tbl_list tbody tr, .board_list tbody tr")

        for item in items:
            try:
                title_el = item.select_one("a, .title, .subject")
                if not title_el:
                    continue

                title = title_el.get_text(strip=True)
                link = title_el.get("href", "")
                if link and not link.startswith("http"):
                    link = BASE_URL + link

                # 주관기관 추출
                org_el = item.select_one(".org, .agency, td:nth-child(2)")
                organizer = org_el.get_text(strip=True) if org_el else ""

                # 날짜 추출
                date_el = item.select_one(".date, .period, td:nth-child(3)")
                date_text = date_el.get_text(strip=True) if date_el else ""

                events.append(ScrapedEvent(
                    title=title,
                    organizer=organizer or "K-Startup",
                    org_type="government",
                    event_type="스타트업 지원",
                    url=link,
                    description=date_text,
                    source=self.source_name,
                ))
            except Exception as e:
                logger.warning(f"[k-startup] 항목 파싱 실패: {e}")
                continue

        logger.info(f"[k-startup] {len(events)}개 행사 수집 완료")
        return events

    async def scrape_organizations(self) -> list[ScrapedOrg]:
        """K-Startup 관련 주관기관 수집."""
        orgs: list[ScrapedOrg] = []

        # 주관기관 목록 페이지에서 기관 정보 수집
        events = await self.scrape_events()

        seen_orgs: set[str] = set()
        for event in events:
            if event.organizer and event.organizer not in seen_orgs:
                seen_orgs.add(event.organizer)
                orgs.append(ScrapedOrg(
                    name=event.organizer,
                    org_type="government",
                    source=self.source_name,
                    events=[event],
                ))

        return orgs
