"""Lead Hunter 데이터베이스 모델."""

from datetime import datetime
from sqlalchemy import (
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    Boolean,
    Table,
)
from sqlalchemy.orm import DeclarativeBase, relationship
import enum


class Base(DeclarativeBase):
    """SQLAlchemy Base."""
    pass


class LeadStatus(str, enum.Enum):
    """리드 상태."""
    NEW = "new"                    # 신규 수집
    VERIFIED = "verified"          # 이메일 검증 완료
    CONTACTED = "contacted"        # 콜드메일 발송 완료
    OPENED = "opened"              # 메일 오픈
    CLICKED = "clicked"            # 링크 클릭
    REPLIED = "replied"            # 회신 받음
    INTERESTED = "interested"      # 관심 표명
    NOT_INTERESTED = "not_interested"  # 관심 없음
    BOUNCED = "bounced"            # 메일 반송


class OrgType(str, enum.Enum):
    """기관 유형."""
    GOVERNMENT = "government"          # 정부 부처
    LOCAL_GOV = "local_government"     # 지자체
    PUBLIC_AGENCY = "public_agency"    # 공공기관/산하기관
    ACCELERATOR = "accelerator"       # 액셀러레이터
    VC = "vc"                         # 벤처캐피탈
    PRIVATE = "private"               # 민간 기업
    ASSOCIATION = "association"        # 협회/단체
    UNIVERSITY = "university"         # 대학교
    OTHER = "other"


# 기관 - 상품 관심 매핑 (다대다)
org_product_interest = Table(
    "org_product_interest",
    Base.metadata,
    Column("organization_id", Integer, ForeignKey("organizations.id")),
    Column("product_id", Integer, ForeignKey("products.id")),
)


class Organization(Base):
    """행사 주최/주관 기관."""

    __tablename__ = "organizations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(200), nullable=False, index=True)
    org_type = Column(Enum(OrgType), nullable=False)
    website = Column(String(500))
    address = Column(String(500))
    description = Column(Text)

    # 관계
    contacts = relationship("Contact", back_populates="organization", cascade="all, delete-orphan")
    events = relationship("Event", back_populates="organization", cascade="all, delete-orphan")
    interested_products = relationship("Product", secondary=org_product_interest)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Contact(Base):
    """담당자 정보 (리드)."""

    __tablename__ = "contacts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False)
    name = Column(String(100))
    department = Column(String(200))       # 담당부서
    position = Column(String(100))         # 직책
    email = Column(String(200), index=True)
    phone = Column(String(50))
    status = Column(Enum(LeadStatus), default=LeadStatus.NEW)
    source = Column(String(200))           # 수집 출처
    notes = Column(Text)

    # 관계
    organization = relationship("Organization", back_populates="contacts")
    email_logs = relationship("EmailLog", back_populates="contact", cascade="all, delete-orphan")

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Event(Base):
    """행사 정보."""

    __tablename__ = "events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False)
    title = Column(String(500), nullable=False)
    event_type = Column(String(100))       # 밋업, 컨퍼런스, 네트워킹, 전시회 등
    description = Column(Text)
    start_date = Column(DateTime)
    end_date = Column(DateTime)
    location = Column(String(500))
    url = Column(String(500))              # 행사 상세 URL
    budget_info = Column(String(200))      # 예산 정보 (있는 경우)
    source = Column(String(200))           # 수집 출처

    # 관계
    organization = relationship("Organization", back_populates="events")

    created_at = Column(DateTime, default=datetime.utcnow)


class Product(Base):
    """판매 상품 (확장 가능)."""

    __tablename__ = "products"

    id = Column(Integer, primary_key=True, autoincrement=True)
    slug = Column(String(100), unique=True, nullable=False)    # meetup-matcher, key-visual
    name = Column(String(200), nullable=False)
    description = Column(Text)
    demo_url = Column(String(500))
    proposal_pdf_path = Column(String(500))
    is_active = Column(Boolean, default=True)

    created_at = Column(DateTime, default=datetime.utcnow)


class EmailLog(Base):
    """이메일 발송 기록."""

    __tablename__ = "email_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    contact_id = Column(Integer, ForeignKey("contacts.id"), nullable=False)
    product_slug = Column(String(100))     # 어떤 상품으로 연락했는지
    subject = Column(String(500))
    template_name = Column(String(100))
    sent_at = Column(DateTime)
    opened_at = Column(DateTime)
    clicked_at = Column(DateTime)
    replied_at = Column(DateTime)
    bounced = Column(Boolean, default=False)
    error_message = Column(Text)

    # 관계
    contact = relationship("Contact", back_populates="email_logs")

    created_at = Column(DateTime, default=datetime.utcnow)
