"""Lead Hunter 대시보드 + API 서버."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

import csv
import io

from fastapi import FastAPI, Depends, Request, Query, UploadFile, File, Form
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import settings
from database import init_db, get_db
from database.models import (
    Organization, Contact, Event, EmailLog, Product,
    LeadStatus, OrgType,
)
from scraper.engine import CrawlEngine
from mailer.sender import ColdMailer

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DASHBOARD_DIR = Path(__file__).parent


@asynccontextmanager
async def lifespan(app: FastAPI):
    """앱 시작/종료 시 실행."""
    await init_db()
    logger.info("🚀 Lead Hunter 시작!")
    yield
    logger.info("Lead Hunter 종료")


app = FastAPI(
    title="Lead Hunter",
    description="행사 주최사 리드 수집 & 콜드메일 자동화",
    version="1.0.0",
    lifespan=lifespan,
)

app.mount("/static", StaticFiles(directory=str(DASHBOARD_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(DASHBOARD_DIR / "templates"))


# ─── 대시보드 페이지 ───

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, db: AsyncSession = Depends(get_db)):
    """메인 대시보드."""
    # 통계 조회
    org_count = (await db.execute(select(func.count(Organization.id)))).scalar() or 0
    contact_count = (await db.execute(select(func.count(Contact.id)))).scalar() or 0
    event_count = (await db.execute(select(func.count(Event.id)))).scalar() or 0
    email_count = (await db.execute(
        select(func.count(EmailLog.id)).where(EmailLog.sent_at.isnot(None))
    )).scalar() or 0

    # 상태별 리드 수
    status_stats = {}
    for status in LeadStatus:
        count = (await db.execute(
            select(func.count(Contact.id)).where(Contact.status == status)
        )).scalar() or 0
        status_stats[status.value] = count

    # 최근 수집 기관
    recent_orgs_result = await db.execute(
        select(Organization).order_by(desc(Organization.created_at)).limit(10)
    )
    recent_orgs = recent_orgs_result.scalars().all()

    # 최근 행사
    recent_events_result = await db.execute(
        select(Event).order_by(desc(Event.created_at)).limit(10)
    )
    recent_events = recent_events_result.scalars().all()

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "stats": {
            "organizations": org_count,
            "contacts": contact_count,
            "events": event_count,
            "emails_sent": email_count,
        },
        "status_stats": status_stats,
        "recent_orgs": recent_orgs,
        "recent_events": recent_events,
    })


@app.get("/leads", response_class=HTMLResponse)
async def leads_page(
    request: Request,
    page: int = Query(1, ge=1),
    status: str | None = None,
    org_type: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """리드 목록 페이지."""
    per_page = 50
    query = select(Contact).join(Organization)

    if status:
        query = query.where(Contact.status == LeadStatus(status))
    if org_type:
        query = query.where(Organization.org_type == OrgType(org_type))

    query = query.order_by(desc(Contact.created_at))
    total = (await db.execute(
        select(func.count()).select_from(query.subquery())
    )).scalar() or 0

    query = query.offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    contacts = result.scalars().all()

    return templates.TemplateResponse("leads.html", {
        "request": request,
        "contacts": contacts,
        "page": page,
        "total": total,
        "total_pages": (total + per_page - 1) // per_page,
        "status_filter": status,
        "org_type_filter": org_type,
        "statuses": [s.value for s in LeadStatus],
        "org_types": [t.value for t in OrgType],
    })


@app.get("/organizations", response_class=HTMLResponse)
async def organizations_page(
    request: Request,
    page: int = Query(1, ge=1),
    db: AsyncSession = Depends(get_db),
):
    """기관 목록 페이지."""
    per_page = 50
    query = select(Organization).order_by(desc(Organization.created_at))

    total = (await db.execute(select(func.count(Organization.id)))).scalar() or 0
    query = query.offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    orgs = result.scalars().all()

    return templates.TemplateResponse("organizations.html", {
        "request": request,
        "organizations": orgs,
        "page": page,
        "total": total,
        "total_pages": (total + per_page - 1) // per_page,
    })


@app.get("/events", response_class=HTMLResponse)
async def events_page(
    request: Request,
    page: int = Query(1, ge=1),
    db: AsyncSession = Depends(get_db),
):
    """행사 목록 페이지."""
    per_page = 50
    query = select(Event).order_by(desc(Event.created_at))

    total = (await db.execute(select(func.count(Event.id)))).scalar() or 0
    query = query.offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    events = result.scalars().all()

    return templates.TemplateResponse("events_list.html", {
        "request": request,
        "events": events,
        "page": page,
        "total": total,
        "total_pages": (total + per_page - 1) // per_page,
    })


# ─── API 엔드포인트 ───

@app.post("/api/crawl")
async def run_crawl(
    source: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """크롤링 실행."""
    engine = CrawlEngine(db)
    if source:
        stats = await engine.run_single(source)
    else:
        stats = await engine.run_all()
    return {"status": "success", "stats": stats}


@app.post("/api/send-campaign")
async def send_campaign(
    product_slug: str,
    template_name: str = "default",
    max_count: int = 10,
    db: AsyncSession = Depends(get_db),
):
    """콜드메일 캠페인 발송."""
    mailer = ColdMailer(db)
    stats = await mailer.send_campaign(
        product_slug=product_slug,
        template_name=template_name,
        max_count=max_count,
    )
    return {"status": "success", "stats": stats}


# ─── 데이터 업로드 페이지 ───

@app.get("/upload", response_class=HTMLResponse)
async def upload_page(request: Request):
    """데이터 업로드 페이지 (정부 입찰/외부 데이터)."""
    return templates.TemplateResponse("upload.html", {"request": request})


@app.post("/api/upload-csv")
async def upload_csv(
    file: UploadFile = File(...),
    data_type: str = Form("bid"),
    db: AsyncSession = Depends(get_db),
):
    """CSV/엑셀 파일 업로드 → DB 저장.

    data_type:
        - bid: 정부 입찰 데이터 (발주기관, 부서, 담당자, 낙찰업체 등)
        - org: 기관 데이터
        - contact: 담당자 데이터
    """
    stats = {"organizations": 0, "contacts": 0, "events": 0, "skipped": 0}

    content = await file.read()
    # UTF-8 또는 EUC-KR 디코딩
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = content.decode("euc-kr", errors="replace")

    reader = csv.DictReader(io.StringIO(text))
    headers = reader.fieldnames or []

    # 헤더 자동 매핑 (유연하게)
    header_map = _detect_headers(headers)

    for row in reader:
        try:
            # 기관 정보 추출
            org_name = _get_value(row, header_map, "org_name")
            if not org_name:
                stats["skipped"] += 1
                continue

            # 기관 찾기 또는 생성
            result = await db.execute(
                select(Organization).where(Organization.name == org_name)
            )
            org = result.scalar_one_or_none()

            if not org:
                dept = _get_value(row, header_map, "department")
                org_type_str = _get_value(row, header_map, "org_type")
                org_type = _guess_org_type(org_name, org_type_str)

                org = Organization(
                    name=org_name,
                    org_type=org_type,
                    description=dept or "",
                )
                db.add(org)
                await db.flush()
                stats["organizations"] += 1

            # 담당자 정보
            contact_name = _get_value(row, header_map, "contact_name")
            contact_email = _get_value(row, header_map, "email")
            contact_phone = _get_value(row, header_map, "phone")
            department = _get_value(row, header_map, "department")

            if contact_email:
                existing = await db.execute(
                    select(Contact).where(Contact.email == contact_email)
                )
                if not existing.scalar_one_or_none():
                    contact = Contact(
                        organization_id=org.id,
                        name=contact_name or "",
                        department=department or "",
                        email=contact_email,
                        phone=contact_phone or "",
                        source=f"upload:{file.filename}",
                    )
                    db.add(contact)
                    stats["contacts"] += 1

            # 입찰/행사 정보
            event_title = _get_value(row, header_map, "event_title")
            if event_title:
                event = Event(
                    organization_id=org.id,
                    title=event_title,
                    event_type=data_type,
                    description=_get_value(row, header_map, "description") or "",
                    budget_info=_get_value(row, header_map, "budget") or "",
                    source=f"upload:{file.filename}",
                )
                db.add(event)
                stats["events"] += 1

            # 낙찰 업체 정보 (입찰 데이터)
            winner = _get_value(row, header_map, "winner")
            if winner:
                result2 = await db.execute(
                    select(Organization).where(Organization.name == winner)
                )
                if not result2.scalar_one_or_none():
                    winner_org = Organization(
                        name=winner,
                        org_type=OrgType.PRIVATE,
                        description="낙찰업체",
                    )
                    db.add(winner_org)
                    stats["organizations"] += 1

        except Exception as e:
            logger.warning(f"행 처리 실패: {e}")
            stats["skipped"] += 1
            continue

    await db.commit()
    logger.info(f"업로드 완료: {stats}")
    return {"status": "success", "filename": file.filename, "stats": stats}


def _detect_headers(headers: list[str]) -> dict[str, str]:
    """CSV 헤더를 자동 감지하여 내부 필드명으로 매핑."""
    mapping = {}
    rules = {
        "org_name": ["발주기관", "기관명", "발주처", "주최기관", "organization", "기관", "발주"],
        "department": ["부서", "부서명", "담당부서", "department", "dept"],
        "contact_name": ["담당자", "담당자명", "성명", "이름", "contact", "name"],
        "email": ["이메일", "email", "e-mail", "메일"],
        "phone": ["전화", "전화번호", "연락처", "phone", "tel"],
        "event_title": ["공고명", "사업명", "입찰명", "행사명", "건명", "title", "과업명"],
        "budget": ["예산", "금액", "낙찰금액", "계약금액", "예정가격", "budget", "amount"],
        "winner": ["낙찰업체", "낙찰자", "계약업체", "수주업체", "winner"],
        "org_type": ["기관유형", "유형", "type"],
        "description": ["내용", "설명", "비고", "description"],
    }

    for h in headers:
        h_lower = h.strip().lower()
        for field, keywords in rules.items():
            if field not in mapping:
                for kw in keywords:
                    if kw.lower() in h_lower:
                        mapping[field] = h.strip()
                        break
    return mapping


def _get_value(row: dict, header_map: dict, field: str) -> str:
    """매핑된 헤더로 값 추출."""
    col = header_map.get(field)
    if col and col in row:
        return row[col].strip()
    return ""


def _guess_org_type(name: str, type_str: str) -> OrgType:
    """기관명이나 유형 문자열로 OrgType 추론."""
    combined = f"{name} {type_str}".lower()
    if any(kw in combined for kw in ["정부", "부", "처", "청", "국방", "행정"]):
        return OrgType.GOVERNMENT
    if any(kw in combined for kw in ["시", "도", "군", "구", "지자체"]):
        return OrgType.LOCAL_GOV
    if any(kw in combined for kw in ["진흥원", "공사", "공단", "센터", "재단", "연구원"]):
        return OrgType.PUBLIC_AGENCY
    if any(kw in combined for kw in ["대학", "학교"]):
        return OrgType.UNIVERSITY
    if any(kw in combined for kw in ["협회", "조합", "연합"]):
        return OrgType.ASSOCIATION
    return OrgType.OTHER


@app.get("/api/stats")
async def get_stats(db: AsyncSession = Depends(get_db)):
    """통계 API."""
    org_count = (await db.execute(select(func.count(Organization.id)))).scalar() or 0
    contact_count = (await db.execute(select(func.count(Contact.id)))).scalar() or 0
    event_count = (await db.execute(select(func.count(Event.id)))).scalar() or 0
    email_count = (await db.execute(
        select(func.count(EmailLog.id)).where(EmailLog.sent_at.isnot(None))
    )).scalar() or 0

    return {
        "organizations": org_count,
        "contacts": contact_count,
        "events": event_count,
        "emails_sent": email_count,
    }
