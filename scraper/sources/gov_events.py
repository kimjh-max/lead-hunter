"""정부/지자체 행사 크롤러 - 나라장터, 정부24, 지자체 행사 수집."""

import logging
import re
from datetime import datetime

from scraper.base import BaseScraper, ScrapedEvent, ScrapedOrg

logger = logging.getLogger(__name__)


# 주요 정부/지자체 행사 관련 사이트
GOV_SOURCES = {
    "정책브리핑": "https://www.korea.kr/news/policyBriefingList.do",
    "중소벤처기업부": "https://www.mss.go.kr/site/smba/ex/bbs/List.do?cbIdx=86",
    "과학기술정보통신부": "https://www.msit.go.kr/bbs/list.do?sCode=user&mId=113&mPid=112",
    "문화체육관광부": "https://www.mcst.go.kr/kor/s_notice/press/pressList.jsp",
}

# 주요 창조경제혁신센터 / 테크노파크
PUBLIC_AGENCIES = [
    {"name": "서울창조경제혁신센터", "url": "https://ccei.creativekorea.or.kr/seoul/", "type": "public_agency"},
    {"name": "경기창조경제혁신센터", "url": "https://ccei.creativekorea.or.kr/gyeonggi/", "type": "public_agency"},
    {"name": "부산창조경제혁신센터", "url": "https://ccei.creativekorea.or.kr/busan/", "type": "public_agency"},
    {"name": "대전창조경제혁신센터", "url": "https://ccei.creativekorea.or.kr/daejeon/", "type": "public_agency"},
    {"name": "인천창조경제혁신센터", "url": "https://ccei.creativekorea.or.kr/incheon/", "type": "public_agency"},
    {"name": "광주창조경제혁신센터", "url": "https://ccei.creativekorea.or.kr/gwangju/", "type": "public_agency"},
    {"name": "대구창조경제혁신센터", "url": "https://ccei.creativekorea.or.kr/daegu/", "type": "public_agency"},
    {"name": "울산창조경제혁신센터", "url": "https://ccei.creativekorea.or.kr/ulsan/", "type": "public_agency"},
    {"name": "세종창조경제혁신센터", "url": "https://ccei.creativekorea.or.kr/sejong/", "type": "public_agency"},
    {"name": "강원창조경제혁신센터", "url": "https://ccei.creativekorea.or.kr/gangwon/", "type": "public_agency"},
    {"name": "충북창조경제혁신센터", "url": "https://ccei.creativekorea.or.kr/chungbuk/", "type": "public_agency"},
    {"name": "충남창조경제혁신센터", "url": "https://ccei.creativekorea.or.kr/chungnam/", "type": "public_agency"},
    {"name": "전북창조경제혁신센터", "url": "https://ccei.creativekorea.or.kr/jeonbuk/", "type": "public_agency"},
    {"name": "전남창조경제혁신센터", "url": "https://ccei.creativekorea.or.kr/jeonnam/", "type": "public_agency"},
    {"name": "경북창조경제혁신센터", "url": "https://ccei.creativekorea.or.kr/gyeongbuk/", "type": "public_agency"},
    {"name": "경남창조경제혁신센터", "url": "https://ccei.creativekorea.or.kr/gyeongnam/", "type": "public_agency"},
    {"name": "제주창조경제혁신센터", "url": "https://ccei.creativekorea.or.kr/jeju/", "type": "public_agency"},
    {"name": "서울테크노파크", "url": "https://www.seoultp.or.kr", "type": "public_agency"},
    {"name": "경기테크노파크", "url": "https://www.gyeonggitp.or.kr", "type": "public_agency"},
    {"name": "창업진흥원", "url": "https://www.kised.or.kr", "type": "public_agency"},
    {"name": "정보통신산업진흥원", "url": "https://www.nipa.kr", "type": "public_agency"},
    {"name": "한국콘텐츠진흥원", "url": "https://www.kocca.kr", "type": "public_agency"},
    {"name": "한국관광공사", "url": "https://kto.visitkorea.or.kr", "type": "public_agency"},
    {"name": "코트라(KOTRA)", "url": "https://www.kotra.or.kr", "type": "public_agency"},
]

# 행사 키워드 (정부 보도자료에서 필터링용)
EVENT_KEYWORDS = [
    "밋업", "네트워킹", "컨퍼런스", "포럼", "세미나", "워크숍",
    "데모데이", "피칭", "해커톤", "전시회", "박람회", "페스티벌",
    "창업대회", "경진대회", "설명회", "간담회", "토론회", "축제",
    "행사", "이벤트", "페어", "엑스포",
]


class GovEventsScraper(BaseScraper):
    """정부/지자체 행사 크롤러."""

    source_name = "gov-events"

    async def scrape_events(self) -> list[ScrapedEvent]:
        """정부/지자체 행사 수집."""
        events: list[ScrapedEvent] = []

        # 1. 정책브리핑 등 정부 사이트에서 행사 관련 보도자료 수집
        for source_name, url in GOV_SOURCES.items():
            source_events = await self._scrape_gov_page(source_name, url)
            events.extend(source_events)

        # 2. 창조경제혁신센터들의 행사 수집
        for agency in PUBLIC_AGENCIES:
            agency_events = await self._scrape_agency_events(agency)
            events.extend(agency_events)

        logger.info(f"[gov-events] 총 {len(events)}개 행사 수집 완료")
        return events

    async def _scrape_gov_page(self, source_name: str, url: str) -> list[ScrapedEvent]:
        """정부 사이트 보도자료에서 행사 관련 항목 수집."""
        events: list[ScrapedEvent] = []

        html = await self.fetch(url)
        if not html:
            return events

        soup = self.parse_html(html)
        # 보도자료 목록에서 행사 관련 항목 필터링
        rows = soup.select(
            "tbody tr, .board_list li, .list_item, "
            ".bbs-list-item, .news_list li, ul.list > li"
        )

        for row in rows:
            title_el = row.select_one("a, .title, .subject, td.subject a")
            if not title_el:
                continue

            title = title_el.get_text(strip=True)

            # 행사 키워드 포함 여부 확인
            if not any(kw in title for kw in EVENT_KEYWORDS):
                continue

            link = title_el.get("href", "")
            if link and not link.startswith("http"):
                # 상대 경로를 절대 경로로 변환
                from urllib.parse import urljoin
                link = urljoin(url, link)

            date_el = row.select_one(".date, .reg_date, td:last-child, time")
            date_text = date_el.get_text(strip=True) if date_el else ""

            dept_el = row.select_one(".dept, .agency, td:nth-child(2)")
            department = dept_el.get_text(strip=True) if dept_el else ""

            events.append(ScrapedEvent(
                title=title,
                organizer=source_name,
                org_type="government",
                event_type="정부 행사",
                description=f"담당: {department}" if department else "",
                contact_department=department,
                url=link,
                source=f"gov-{source_name}",
            ))

        return events

    async def _scrape_agency_events(self, agency: dict) -> list[ScrapedEvent]:
        """공공기관(창조경제혁신센터 등) 행사 수집."""
        events: list[ScrapedEvent] = []

        # 각 기관의 행사/공지 게시판 크롤링
        # 대부분 /board/list 또는 /bbs/list 패턴
        possible_paths = [
            "/board/list.do",
            "/bbs/list.do",
            "/news/event",
            "/program/list",
            "/notice/list",
        ]

        base_url = agency["url"].rstrip("/")

        for path in possible_paths:
            html = await self.fetch(f"{base_url}{path}")
            if not html:
                continue

            soup = self.parse_html(html)
            rows = soup.select(
                "tbody tr, .board_list li, .list_item, "
                ".bbs_list li, ul.list > li"
            )

            for row in rows:
                title_el = row.select_one("a, .title, .subject")
                if not title_el:
                    continue

                title = title_el.get_text(strip=True)
                link = title_el.get("href", "")
                if link and not link.startswith("http"):
                    from urllib.parse import urljoin
                    link = urljoin(f"{base_url}{path}", link)

                events.append(ScrapedEvent(
                    title=title,
                    organizer=agency["name"],
                    org_type="public_agency",
                    event_type="공공기관 행사",
                    url=link,
                    source=f"agency-{agency['name']}",
                ))

            if rows:
                break  # 행사 목록을 찾았으면 다른 경로 시도 불필요

        return events

    async def scrape_organizations(self) -> list[ScrapedOrg]:
        """정부/공공기관 정보 수집."""
        orgs: list[ScrapedOrg] = []

        # 사전 정의된 공공기관 목록
        for agency in PUBLIC_AGENCIES:
            orgs.append(ScrapedOrg(
                name=agency["name"],
                org_type=agency["type"],
                website=agency["url"],
                source=self.source_name,
            ))

        # 행사에서 추가 기관 수집
        events = await self.scrape_events()
        seen = {org.name for org in orgs}

        for event in events:
            if event.organizer and event.organizer not in seen:
                seen.add(event.organizer)
                orgs.append(ScrapedOrg(
                    name=event.organizer,
                    org_type=event.org_type,
                    source=self.source_name,
                    events=[event],
                ))

        return orgs
