"""Eventbrite 크롤러 - 국내외 행사 수집."""

import logging
from datetime import datetime

from scraper.base import BaseScraper, ScrapedEvent, ScrapedOrg

logger = logging.getLogger(__name__)

BASE_URL = "https://www.eventbrite.com"
SEARCH_URL = f"{BASE_URL}/d/online/startup-networking"
SEARCH_QUERIES = [
    "startup-networking",
    "meetup-networking",
    "tech-conference",
    "startup-pitch",
    "business-networking",
]


class EventbriteScraper(BaseScraper):
    """Eventbrite 행사 크롤러."""

    source_name = "eventbrite"

    async def scrape_events(self) -> list[ScrapedEvent]:
        """Eventbrite에서 스타트업/밋업 행사 수집."""
        events: list[ScrapedEvent] = []

        for query in SEARCH_QUERIES:
            url = f"{BASE_URL}/d/online/{query}/"
            html = await self.fetch(url)
            if not html:
                continue

            soup = self.parse_html(html)
            cards = soup.select(
                "[class*='event-card'], [data-testid*='event'], "
                ".search-event-card, article"
            )

            for card in cards:
                title_el = card.select_one(
                    "h2, h3, [class*='title'], [data-testid*='title']"
                )
                if not title_el:
                    continue

                title = title_el.get_text(strip=True)
                link_el = card.select_one("a[href*='/e/']")
                link = link_el["href"] if link_el else ""

                org_el = card.select_one(
                    "[class*='organizer'], [class*='host'], "
                    "[data-testid*='organizer']"
                )
                organizer = org_el.get_text(strip=True) if org_el else ""

                date_el = card.select_one(
                    "[class*='date'], time, [data-testid*='date']"
                )
                date_text = date_el.get_text(strip=True) if date_el else ""

                location_el = card.select_one(
                    "[class*='location'], [class*='venue'], "
                    "[data-testid*='location']"
                )
                location = location_el.get_text(strip=True) if location_el else ""

                events.append(ScrapedEvent(
                    title=title,
                    organizer=organizer,
                    org_type="private",
                    event_type=query.replace("-", " "),
                    description=date_text,
                    location=location,
                    url=link,
                    source=self.source_name,
                ))

        logger.info(f"[eventbrite] {len(events)}개 행사 수집 완료")
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
