"""Lead Hunter 실행 스크립트."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

import uvicorn

# 프로젝트 루트를 path에 추가
sys.path.insert(0, str(Path(__file__).parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("lead-hunter")


async def run_crawl(source: str | None = None) -> None:
    """크롤링 실행."""
    from database.session import init_db, async_session
    from scraper.engine import CrawlEngine

    await init_db()

    async with async_session() as db:
        engine = CrawlEngine(db)
        if source:
            logger.info(f"단일 소스 크롤링: {source}")
            stats = await engine.run_single(source)
        else:
            logger.info("전체 소스 크롤링 시작")
            stats = await engine.run_all()

    logger.info(f"크롤링 완료: {stats}")


async def run_campaign(product: str, count: int) -> None:
    """콜드메일 캠페인 실행."""
    from database.session import init_db, async_session
    from mailer.sender import ColdMailer

    await init_db()

    async with async_session() as db:
        mailer = ColdMailer(db)
        stats = await mailer.send_campaign(
            product_slug=product,
            max_count=count,
        )

    logger.info(f"캠페인 완료: {stats}")


def run_dashboard(host: str = "0.0.0.0", port: int = 8500) -> None:
    """대시보드 서버 실행."""
    logger.info(f"Lead Hunter 대시보드 시작: http://localhost:{port}")
    uvicorn.run(
        "dashboard.app:app",
        host=host,
        port=port,
        reload=True,
    )


def main() -> None:
    """CLI 엔트리포인트."""
    parser = argparse.ArgumentParser(
        description="🎯 Lead Hunter - 행사 주최사 리드 수집 & 콜드메일 자동화"
    )
    subparsers = parser.add_subparsers(dest="command", help="실행할 명령")

    # 대시보드
    dash_parser = subparsers.add_parser("dashboard", help="대시보드 서버 실행")
    dash_parser.add_argument("--port", type=int, default=8500)
    dash_parser.add_argument("--host", default="0.0.0.0")

    # 크롤링
    crawl_parser = subparsers.add_parser("crawl", help="크롤링 실행")
    crawl_parser.add_argument("--source", help="특정 소스만 크롤링 (예: festa, k-startup)")

    # 캠페인
    campaign_parser = subparsers.add_parser("campaign", help="콜드메일 캠페인 발송")
    campaign_parser.add_argument("--product", required=True, help="상품 slug (meetup-matcher, key-visual)")
    campaign_parser.add_argument("--count", type=int, default=10, help="최대 발송 수")

    args = parser.parse_args()

    if args.command == "dashboard":
        run_dashboard(host=args.host, port=args.port)
    elif args.command == "crawl":
        asyncio.run(run_crawl(args.source))
    elif args.command == "campaign":
        asyncio.run(run_campaign(args.product, args.count))
    else:
        parser.print_help()
        print("\n사용 예시:")
        print("  python run.py dashboard          # 대시보드 실행")
        print("  python run.py crawl               # 전체 크롤링")
        print("  python run.py crawl --source festa # Festa만 크롤링")
        print("  python run.py campaign --product meetup-matcher --count 10")


if __name__ == "__main__":
    main()
