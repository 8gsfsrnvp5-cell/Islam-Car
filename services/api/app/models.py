"""Схема базы данных Islamic Car.

Деньги — целые копейки (BigInteger). Первичные ключи — UUID, чтобы не раскрывать
объёмы бизнеса последовательными номерами. Записи о деньгах не удаляются.
"""

import enum
import uuid
from datetime import UTC, date, datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


def str_enum(cls: type[enum.Enum]) -> Enum:
    return Enum(cls, native_enum=False, length=32, validate_strings=True,
                values_callable=lambda e: [m.value for m in e])


class Role(enum.StrEnum):
    owner = "owner"
    admin = "admin"
    manager = "manager"
    accountant = "accountant"
    client = "client"


class Realm(enum.StrEnum):
    admin = "admin"
    client = "client"


class OwnershipStatus(enum.StrEnum):
    owned = "owned"            # в собственности продавца, может быть передан
    purchasing = "purchasing"  # в процессе закупки, продать пока нельзя


class CarStatus(enum.StrEnum):
    draft = "draft"
    available = "available"
    reserved = "reserved"
    sold = "sold"
    archived = "archived"


class ApplicationKind(enum.StrEnum):
    catalog = "catalog"            # заявка на автомобиль из каталога
    custom_order = "custom_order"  # заказ автомобиля, которого нет в каталоге


class ApplicationStatus(enum.StrEnum):
    new = "new"
    in_progress = "in_progress"
    info_requested = "info_requested"
    offer_made = "offer_made"
    converted = "converted"  # по заявке заключён договор
    rejected = "rejected"
    withdrawn = "withdrawn"


class PartyType(enum.StrEnum):
    individual = "individual"  # физическое лицо
    ip = "ip"                  # индивидуальный предприниматель
    llc = "llc"                # ООО


class SellerRegime(enum.StrEnum):
    individual_one_off = "individual_one_off"  # разовая продажа личного имущества
    ip = "ip"
    llc = "llc"


class ContractStatus(enum.StrEnum):
    draft = "draft"
    signed = "signed"        # действующий
    completed = "completed"  # обязательства исполнены полностью
    cancelled = "cancelled"  # черновик отменён до подписания


class ScheduleKind(enum.StrEnum):
    down_payment = "down_payment"
    installment = "installment"


class PaymentStatus(enum.StrEnum):
    confirmed = "confirmed"
    reversed = "reversed"


class PaymentMethod(enum.StrEnum):
    bank_transfer = "bank_transfer"
    cash = "cash"
    card = "card"
    other = "other"


class PaymentReportStatus(enum.StrEnum):
    pending = "pending"
    matched = "matched"
    rejected = "rejected"


class ThreadTopic(enum.StrEnum):
    general = "general"
    payment_difficulty = "payment_difficulty"
    schedule_change = "schedule_change"
    early_repayment = "early_repayment"
    documents = "documents"


class ThreadStatus(enum.StrEnum):
    open = "open"
    answered = "answered"
    closed = "closed"


class Audience(enum.StrEnum):
    staff = "staff"
    client = "client"


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    login: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(200))
    role: Mapped[Role] = mapped_column(str_enum(Role))
    password_hash: Mapped[str | None] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    totp_secret: Mapped[str | None] = mapped_column(String(64))
    totp_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    client_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("clients.id"), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    client: Mapped["Client | None"] = relationship(back_populates="user", foreign_keys=[client_id])


class Session_(Base):
    """Серверная сессия: в cookie лежит случайный токен, в базе — только его хеш."""

    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    realm: Mapped[Realm] = mapped_column(str_enum(Realm))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ip: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(300))

    user: Mapped[User] = relationship()


class LoginAttempt(Base):
    __tablename__ = "login_attempts"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    login: Mapped[str] = mapped_column(String(120), index=True)
    ip: Mapped[str | None] = mapped_column(String(64))
    success: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class ActivationToken(Base):
    """Одноразовая ссылка для установки пароля покупателем (выдаётся сотрудником)."""

    __tablename__ = "activation_tokens"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CompanySettings(Base):
    """Одна строка: режим продавца, реквизиты для оплаты, счётчик номеров договоров."""

    __tablename__ = "company_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    seller_regime: Mapped[SellerRegime] = mapped_column(str_enum(SellerRegime), default=SellerRegime.ip)
    seller_name: Mapped[str] = mapped_column(String(300), default="")
    seller_inn: Mapped[str] = mapped_column(String(12), default="")
    seller_ogrn: Mapped[str] = mapped_column(String(15), default="")
    seller_address: Mapped[str] = mapped_column(String(500), default="")
    support_phone: Mapped[str] = mapped_column(String(32), default="")
    bank_payee: Mapped[str] = mapped_column(String(300), default="")
    bank_name: Mapped[str] = mapped_column(String(300), default="")
    bank_bik: Mapped[str] = mapped_column(String(9), default="")
    bank_account: Mapped[str] = mapped_column(String(20), default="")
    bank_corr_account: Mapped[str] = mapped_column(String(20), default="")
    payment_purpose_hint: Mapped[str] = mapped_column(String(300), default="Оплата по договору № {number}")
    contract_prefix: Mapped[str] = mapped_column(String(16), default="IC")
    next_contract_seq: Mapped[int] = mapped_column(Integer, default=1)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Car(Base):
    __tablename__ = "cars"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    vin: Mapped[str | None] = mapped_column(String(17), unique=True, index=True)
    make: Mapped[str] = mapped_column(String(80), index=True)
    model: Mapped[str] = mapped_column(String(80), index=True)
    year: Mapped[int] = mapped_column(Integer)
    mileage_km: Mapped[int] = mapped_column(Integer, default=0)
    body_type: Mapped[str] = mapped_column(String(60), default="")
    engine: Mapped[str] = mapped_column(String(120), default="")
    transmission: Mapped[str] = mapped_column(String(60), default="")
    drive: Mapped[str] = mapped_column(String(60), default="")
    color: Mapped[str] = mapped_column(String(60), default="")
    trim: Mapped[str] = mapped_column(Text, default="")
    condition: Mapped[str] = mapped_column(Text, default="")
    description: Mapped[str] = mapped_column(Text, default="")

    ownership_status: Mapped[OwnershipStatus] = mapped_column(
        str_enum(OwnershipStatus), default=OwnershipStatus.purchasing)
    status: Mapped[CarStatus] = mapped_column(str_enum(CarStatus), default=CarStatus.draft, index=True)
    is_published: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    # Коммерческая тайна: только для сотрудников
    purchase_price_kopecks: Mapped[int | None] = mapped_column(BigInteger)
    purchase_date: Mapped[date | None] = mapped_column(Date)
    purchase_document: Mapped[str] = mapped_column(String(300), default="")

    # Публичные условия
    sale_price_kopecks: Mapped[int] = mapped_column(BigInteger)
    min_down_payment_kopecks: Mapped[int | None] = mapped_column(BigInteger)
    max_term_months: Mapped[int | None] = mapped_column(Integer)

    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    photos: Mapped[list["CarPhoto"]] = relationship(
        back_populates="car", order_by="CarPhoto.position", cascade="all, delete-orphan")


class CarPhoto(Base):
    __tablename__ = "car_photos"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    car_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cars.id"), index=True)
    file_name: Mapped[str] = mapped_column(String(120))
    content_type: Mapped[str] = mapped_column(String(40))
    position: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    car: Mapped[Car] = relationship(back_populates="photos")


class Client(Base):
    __tablename__ = "clients"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    party_type: Mapped[PartyType] = mapped_column(str_enum(PartyType), default=PartyType.individual)
    full_name: Mapped[str] = mapped_column(String(300), index=True)
    phone: Mapped[str] = mapped_column(String(16), index=True)
    email: Mapped[str] = mapped_column(String(200), default="")
    address: Mapped[str] = mapped_column(String(500), default="")
    birth_date: Mapped[date | None] = mapped_column(Date)
    passport_number: Mapped[str] = mapped_column(String(20), default="")
    passport_issued_by: Mapped[str] = mapped_column(String(300), default="")
    passport_issue_date: Mapped[date | None] = mapped_column(Date)
    inn: Mapped[str] = mapped_column(String(12), default="")
    ogrn: Mapped[str] = mapped_column(String(15), default="")
    kpp: Mapped[str] = mapped_column(String(9), default="")
    representative: Mapped[str] = mapped_column(String(300), default="")
    timezone: Mapped[str] = mapped_column(String(40), default="Europe/Moscow")
    identity_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    identity_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    identity_verified_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", use_alter=True, name="fk_clients_identity_verified_by"))
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    user: Mapped[User | None] = relationship(back_populates="client", foreign_keys=[User.client_id])


class Application(Base):
    __tablename__ = "applications"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    public_token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    kind: Mapped[ApplicationKind] = mapped_column(str_enum(ApplicationKind))
    status: Mapped[ApplicationStatus] = mapped_column(
        str_enum(ApplicationStatus), default=ApplicationStatus.new, index=True)
    car_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("cars.id"))
    client_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("clients.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    phone: Mapped[str] = mapped_column(String(16), index=True)
    desired_down_payment_kopecks: Mapped[int | None] = mapped_column(BigInteger)
    desired_term_months: Mapped[int | None] = mapped_column(Integer)
    comment: Mapped[str] = mapped_column(Text, default="")
    # Поля заказа автомобиля, которого нет в каталоге
    wanted_make: Mapped[str] = mapped_column(String(80), default="")
    wanted_model: Mapped[str] = mapped_column(String(80), default="")
    wanted_year: Mapped[int | None] = mapped_column(Integer)
    wanted_trim: Mapped[str] = mapped_column(Text, default="")
    max_budget_kopecks: Mapped[int | None] = mapped_column(BigInteger)

    consent_personal_data: Mapped[bool] = mapped_column(Boolean)
    consent_version: Mapped[str] = mapped_column(String(32))
    source_ip_hash: Mapped[str | None] = mapped_column(String(64), index=True)  # антиспам, без хранения IP
    public_message: Mapped[str] = mapped_column(Text, default="")
    internal_note: Mapped[str] = mapped_column(Text, default="")
    assigned_to: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    car: Mapped[Car | None] = relationship()
    events: Mapped[list["ApplicationEvent"]] = relationship(
        order_by="ApplicationEvent.created_at", cascade="all, delete-orphan")


class ApplicationEvent(Base):
    __tablename__ = "application_events"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    application_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("applications.id"), index=True)
    from_status: Mapped[str | None] = mapped_column(String(32))
    to_status: Mapped[str] = mapped_column(String(32))
    public_message: Mapped[str] = mapped_column(Text, default="")
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Contract(Base):
    __tablename__ = "contracts"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    number: Mapped[str | None] = mapped_column(String(32), unique=True, index=True)
    status: Mapped[ContractStatus] = mapped_column(
        str_enum(ContractStatus), default=ContractStatus.draft, index=True)
    client_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("clients.id"), index=True)
    car_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cars.id"), index=True)
    application_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("applications.id"))

    seller_regime: Mapped[SellerRegime] = mapped_column(str_enum(SellerRegime))
    buyer_type: Mapped[PartyType] = mapped_column(str_enum(PartyType))
    is_consumer_deal: Mapped[bool] = mapped_column(Boolean)

    purchase_price_kopecks: Mapped[int] = mapped_column(BigInteger)
    sale_price_kopecks: Mapped[int] = mapped_column(BigInteger)
    markup_kopecks: Mapped[int] = mapped_column(BigInteger)
    down_payment_kopecks: Mapped[int] = mapped_column(BigInteger)
    financed_kopecks: Mapped[int] = mapped_column(BigInteger)
    term_months: Mapped[int] = mapped_column(Integer)
    monthly_payment_kopecks: Mapped[int] = mapped_column(BigInteger)
    contract_date: Mapped[date] = mapped_column(Date)
    first_payment_date: Mapped[date] = mapped_column(Date)
    disclose_cost_to_buyer: Mapped[bool] = mapped_column(Boolean, default=True)
    # Без процентов, пеней и штрафов за просрочку — неизменяемое условие модели
    no_interest_on_delay: Mapped[bool] = mapped_column(Boolean, default=True)

    signed_at: Mapped[date | None] = mapped_column(Date)
    signed_confirmed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    client: Mapped[Client] = relationship()
    car: Mapped[Car] = relationship()
    schedule: Mapped[list["ScheduleItem"]] = relationship(
        order_by="ScheduleItem.seq", cascade="all, delete-orphan")
    payments: Mapped[list["Payment"]] = relationship(order_by="Payment.received_on")


class ScheduleItem(Base):
    __tablename__ = "schedule_items"
    __table_args__ = (UniqueConstraint("contract_id", "seq"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    contract_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("contracts.id"), index=True)
    seq: Mapped[int] = mapped_column(Integer)  # 0 — первоначальный взнос
    kind: Mapped[ScheduleKind] = mapped_column(str_enum(ScheduleKind))
    due_date: Mapped[date] = mapped_column(Date, index=True)
    amount_kopecks: Mapped[int] = mapped_column(BigInteger)


class Payment(Base):
    """Поступление денег. Учитывается только подтверждённое сотрудником; не удаляется."""

    __tablename__ = "payments"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    contract_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("contracts.id"), index=True)
    amount_kopecks: Mapped[int] = mapped_column(BigInteger)
    received_on: Mapped[date] = mapped_column(Date, index=True)
    method: Mapped[PaymentMethod] = mapped_column(str_enum(PaymentMethod))
    document_ref: Mapped[str] = mapped_column(String(120))
    note: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[PaymentStatus] = mapped_column(str_enum(PaymentStatus), default=PaymentStatus.confirmed)
    confirmed_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    confirmed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    reversed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    reversed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reversal_reason: Mapped[str] = mapped_column(Text, default="")
    corrects_payment_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("payments.id"))
    report_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("payment_reports.id"))


class PaymentReport(Base):
    """Сообщение покупателя «Я оплатил». На остаток долга не влияет."""

    __tablename__ = "payment_reports"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    contract_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("contracts.id"), index=True)
    amount_kopecks: Mapped[int] = mapped_column(BigInteger)
    paid_on: Mapped[date] = mapped_column(Date)
    comment: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[PaymentReportStatus] = mapped_column(
        str_enum(PaymentReportStatus), default=PaymentReportStatus.pending, index=True)
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Expense(Base):
    __tablename__ = "expenses"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    spent_on: Mapped[date] = mapped_column(Date, index=True)
    category: Mapped[str] = mapped_column(String(80))
    amount_kopecks: Mapped[int] = mapped_column(BigInteger)
    description: Mapped[str] = mapped_column(Text, default="")
    car_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("cars.id"))
    document_ref: Mapped[str] = mapped_column(String(120), default="")
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SupportThread(Base):
    __tablename__ = "support_threads"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    client_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("clients.id"), index=True)
    contract_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("contracts.id"))
    topic: Mapped[ThreadTopic] = mapped_column(str_enum(ThreadTopic))
    subject: Mapped[str] = mapped_column(String(200))
    status: Mapped[ThreadStatus] = mapped_column(str_enum(ThreadStatus), default=ThreadStatus.open, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    client: Mapped[Client] = relationship()
    messages: Mapped[list["SupportMessage"]] = relationship(order_by="SupportMessage.created_at")


class SupportMessage(Base):
    __tablename__ = "support_messages"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    thread_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("support_threads.id"), index=True)
    author_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    from_staff: Mapped[bool] = mapped_column(Boolean)
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    author: Mapped[User] = relationship()


class Notification(Base):
    """Внутренние уведомления: для сотрудников (общие) или для конкретного покупателя."""

    __tablename__ = "notifications"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    audience: Mapped[Audience] = mapped_column(str_enum(Audience), index=True)
    client_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("clients.id"), index=True)
    kind: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text, default="")
    link: Mapped[str] = mapped_column(String(300), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuditLog(Base):
    """Журнал действий. Только добавление записей."""

    __tablename__ = "audit_log"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), index=True)
    actor_role: Mapped[str | None] = mapped_column(String(32))
    action: Mapped[str] = mapped_column(String(80), index=True)
    entity_type: Mapped[str] = mapped_column(String(40))
    entity_id: Mapped[str | None] = mapped_column(String(64), index=True)
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    ip: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
