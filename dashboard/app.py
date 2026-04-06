"""Lead Hunter 대시보드 + API 서버."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Depends, Request, Query
from fastapi.responses import HTMLResponse
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
