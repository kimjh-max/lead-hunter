"""Lead Hunter 설정 모듈."""

from __future__ import annotations

from pathlib import Path
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """애플리케이션 설정."""

    # 기본 설정
    app_name: str = "Lead Hunter"
    app_version: str = "1.0.0"
    debug: bool = False

    # 데이터베이스
    database_url: str = "sqlite+aiosqlite:///./data/leads.db"

    # 이메일 설정 (콜드메일 발송)
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    sender_name: str = "EpicStage"
    sender_email: str = ""

    # 발송 제한 (스팸 방지)
    max_emails_per_hour: int = 20
    max_emails_per_day: int = 100
    email_interval_seconds: int = 30

    # 크롤링 설정
    crawl_interval_hours: int = 24
    request_delay_seconds: float = 2.0
    max_concurrent_requests: int = 3

    # 프로젝트 경로
    base_dir: Path = Path(__file__).parent.parent
    data_dir: Path = base_dir / "data"
    logs_dir: Path = base_dir / "logs"
    templates_dir: Path = base_dir / "mailer" / "templates"

    # 상품 목록 (확장 가능)
    products: dict[str, dict[str, str]] = {
        "meetup-matcher": {
            "name": "밋업 매칭 프로그램",
            "demo_url": "",
            "description": "AI 기반 네트워킹 매칭 솔루션",
        },
        "key-visual": {
            "name": "키비주얼 생성 프로그램",
            "demo_url": "",
            "description": "AI 기반 행사 키비주얼 자동 생성",
        },
    }

    model_config = {"env_file": ".env", "env_prefix": "LH_"}


settings = Settings()
